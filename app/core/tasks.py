import os.path
import itertools

from celery.utils.log import get_task_logger
from datetime import datetime
from imgcompare import is_equal
from PIL import Image

from app import celery
from app.dl.dl import thumbnail_path
from app.dl.helpers import seconds_to_time
import time


COMPARE_DURATION_THRESHOLD = 0.10
COMPARE_RATIO_THRESHOLD = 0.25
COMPARE_IMAGE_DATA_THRESHOLD = 10.0

log = get_task_logger(__name__)

#
# class SQLAlchemyTask(celery.Task):
#     abstract = True
#
#     def after_return(self, status, retval, task_id, args, kwags, einfo):
#         db_session.remove()


def update_video(video_id: str, status: int, data: dict = {}) -> bool:
    from app.dl.dl import write_metadata

    if len(data.keys()):
        data["status"] = status
        write_metadata(video_id, data)
        return True

    try:
        from app.serve.db import Video, session_scope
        with session_scope() as db_session:
            video = db_session.query(Video).filter_by(video_id=video_id).first()
            if not video:
                return False
            video.status = status

            db_session.add(video)
            db_session.commit()
    except Exception as e:
        log.error(e)
        return False
    return True


def check_duplicate_video(v1, v2) -> bool:
    try:
        if not (v1.duration and v2.duration):
            return False
        elif abs(1.0 - v1.duration / v2.duration) > COMPARE_DURATION_THRESHOLD:
            return False
        elif abs(v1.aspect_ratio - v2.aspect_ratio) > COMPARE_RATIO_THRESHOLD:
            return False

        v1_thumb_path = os.path.join(thumbnail_path, v1.video_id + "_thumb.jpg")
        v2_thumb_path = os.path.join(thumbnail_path, v2.video_id + "_thumb.jpg")

        if os.path.isfile(v1_thumb_path) and os.path.isfile(v2_thumb_path):
            try:
                img1 = Image.open(v1_thumb_path)
                img2 = Image.open(v2_thumb_path)
                img1 = img1.resize((64, 64))
                img2 = img2.resize((64, 64))
                return is_equal(img1, img2, tolerance=COMPARE_IMAGE_DATA_THRESHOLD)

            except Exception as e:
                log.error(e)

    except Exception as e:
        log.error(e)

    return False


@celery.task(name="core.tasks.check_all_duplicates", soft_time_limit=3600, time_limit=3660, priority=9, queue="fast")
def check_all_duplicates_task():
    from app.serve.db import Video, session_scope
    from sqlalchemy import or_
    from app.dl.dl import STATUS_COMPLETED, STATUS_PROCESSING

    total_duplicates = 0
    log.info("Checking all videos for duplicates...")
    with session_scope() as session:
        videos = session.query(Video).filter(or_(
            Video.status == STATUS_PROCESSING, Video.status == STATUS_COMPLETED
        )).all()

        log.info(f"There are {len(videos)} videos to test.")
        for v1, v2 in itertools.combinations(videos, 2):
            if (v1.can_be_changed and v2.can_be_changed) and check_duplicate_video(v1, v2):
                total_duplicates += 1
                if v2 not in v1.duplicates:
                    v1.duplicates.append(v2)
                if v1 not in v2.duplicates:
                    v2.duplicates.append(v1)
            else:
                if v2 in v1.duplicates:
                    v1.duplicates.remove(v2)
                if v1 in v2.duplicates:
                    v2.duplicates.remove(v1)

            session.add(v1)
            session.add(v2)
        session.commit()

    log.info(f"Check is done, found {total_duplicates} duplicates.")
    return total_duplicates


@celery.task(name="core.tasks.gen_thumbnail", soft_time_limit=300, time_limit=360, priority=0, queue="fast")
def gen_images_task(metadata: dict):
    from app.dl.metadata import generate_video_images
    from app.dl.dl import original_path, thumbnail_path, preview_path
    dur = time.time()
    log.info("Generating thumbnail...")

    try:
        video_id = metadata["video_id"]
        duration = metadata["duration"]
        content_warning = metadata["content_warning"]
    except KeyError:
        log.error("Missing data... cant do shit.")
        return

    vid_save_path = os.path.join(original_path, video_id + ".mp4")
    if not os.path.isfile(vid_save_path):
        log.error("No video file to generate images for.")
        return

    generate_video_images(
        vid_save_path,
        os.path.join(thumbnail_path, video_id + "_thumb.jpg"),
        os.path.join(preview_path, video_id + "_preview.jpg"),
        os.path.join(thumbnail_path, video_id + "_thumb_blurred.jpg"),
        os.path.join(preview_path, video_id + "_preview_blurred.jpg"),
        start=5 if duration >= 10.0 else 0,
        blur_amount=0.75,
        desaturate=False,
        content_text=content_warning if content_warning.lower().strip() != "none" else ""
    )
    dur = time.time() - dur
    _hours, minutes, seconds = seconds_to_time(dur)
    log.info(f"Images generated in {minutes} minutes, {seconds:.2f} seconds: {video_id}")


@celery.task(name="core.tasks.post_process", soft_time_limit=10800, time_limit=10860, priority=5, queue="processing")
def post_process_task(data: dict, video_id: str):
    from app.dl.dl import (
        process_from_json_data,
        STATUS_COMPLETED,
        STATUS_FAILED,
        STATUS_PROCESSING,
        original_path, processed_path
    )
    if "video_id" not in data:
        log.error("Bad metadata to process from, aborting task.")
        update_video(video_id, STATUS_COMPLETED)    # Completed == original file
        return

    input_path = os.path.join(original_path, f"{video_id}.mp4")
    output_path = os.path.join(processed_path, f"{video_id}.mp4")
    if not os.path.isfile(input_path):
        log.error("Input file not found, aborting task.")
        update_video(video_id, STATUS_COMPLETED)    # Completed == original file
        return

    dur = time.time()
    log.info("Starting processing of " + str(video_id))

    success = False
    try:
        for data in process_from_json_data(data, input_path, output_path):
            status = data["status"]
            if status == STATUS_PROCESSING:
                log.info(f"Update from post-processing task: {video_id}")
                update_video(video_id, status, data=data)
                continue
            elif status == STATUS_COMPLETED:
                log.info(f"Post-process task has completed with no errors: {video_id}")
                update_video(video_id, status, data=data)
                success = True
                break
            elif status in [STATUS_FAILED]:
                log.info(f"Post-processing for {video_id} has failed.")
                update_video(video_id, status, data=data)
                break
    except Exception as e:
        log.error(e)

    dur = time.time() - dur
    hours, minutes, seconds = seconds_to_time(dur)
    if success:
        try:
            from app.serve.db import Video, session_scope
            with session_scope() as session:
                video = session.query(Video).filter_by(video_id=video_id).first()
                if video:
                    video.status = STATUS_COMPLETED
                    video.post_processed = True
                    session.add(video)
                    session.commit()
        except Exception as e:
            log.error(e)
            log.error("Unable to set status to completed on DB row...")
        if hours > 0:
            log.info(f"Post-process complete in {hours} hours, {minutes} minutes: {video_id}")
        else:
            log.info(f"Post-process complete in {minutes} minutes, {seconds:.0f} seconds: {video_id}")
    else:
        try:
            from app.serve.db import Video, session_scope
            with session_scope() as session:
                video = session.query(Video).filter_by(video_id=video_id).first()
                if video:
                    video.status = STATUS_COMPLETED
                    video.post_processed = False
                    session.add(video)
                    session.commit()
        except Exception as e:
            log.error(e)
            log.error("Unable to set status to completed on DB row...")

        if hours > 0:
            log.error(f"Post-process failed after {hours} hours, {minutes} minutes: {video_id}")
        else:
            log.error(f"Post-process failed after {minutes} minutes, {seconds:.0f} seconds: {video_id}")


@celery.task(name="core.tasks.download", soft_time_limit=14400, time_limit=14700, priority=1, queue="downloads")    #, base=SQLAlchemyTask)
def download_task(data: dict, file_name: str):
    from app.serve.search import index_video_data
    from app.dl.dl import (
        download_from_json_data,
        find_duplicate_video_by_url,
        STATUS_DOWNLOADING,
        STATUS_COMPLETED,
        STATUS_FAILED,
        STATUS_INVALID,
        STATUS_COOKIES,
        STATUS_PENDING,
        STATUS_PROCESSING,
    )

    if "video_id" not in data:
        log.error("Bad metadata to download from, aborting task.")
        return

    dur = time.time()
    log.info("Starting download of " + str(file_name))
    success = False
    try:
        for data in download_from_json_data(data, file_name):
            status = data["status"]
            if status == STATUS_DOWNLOADING:
                log.info("Update from download process...")
                update_video(file_name, status, data=data)
                continue
            elif status == STATUS_COMPLETED:
                log.info("Download function has completed with no errors.")
                update_video(file_name, status, data=data)
                success = True
                break
            elif status in [STATUS_FAILED, STATUS_INVALID, STATUS_COOKIES]:
                log.info("Download function has failed.")
                if status == STATUS_FAILED:
                    log.error("Failure or exception during download.")
                elif status == STATUS_INVALID:
                    log.error("No video on that URL or unhandled formats.")
                elif status == STATUS_COOKIES:
                    log.error("That video needs cookies for geo-locked or age restricted content.")

            update_video(file_name, status, data=data)
            break   # Break on any yield that's not continued above

    except Exception as e:
        log.error(e)

    dur = time.time() - dur
    hours, minutes, seconds = seconds_to_time(dur)
    if success:
        try:
            from app.serve.db import Video, session_scope
            with session_scope() as session:
                video = session.query(Video).filter_by(video_id=file_name).first()
                if video:
                    if video.status != STATUS_COMPLETED:
                        video.status = STATUS_COMPLETED
                        session.add(video)
                        session.commit()
                    index_video_data(video)
        except Exception as e:
            log.error(e)
        if hours > 0:
            log.info(f"Download complete in {hours} hours, {minutes} minutes: {file_name}")
        else:
            log.info(f"Download complete in {minutes} minutes, {seconds:.0f} seconds: {file_name}")
    else:
        try:
            from app.serve.db import Video, session_scope
            with session_scope() as session:
                video = session.query(Video).filter_by(video_id=file_name).first()
                if video:
                    if video.status == STATUS_DOWNLOADING:
                        video.status = STATUS_FAILED
                        session.add(video)
                        session.commit()
        except Exception as e:
            log.error(e)
            log.error("Unable to set status to failed on DB row...")

        if hours > 0:
            log.error(f"Download failed after {hours} hours, {minutes} minutes: {file_name}")
        else:
            log.error(f"Download failed after {minutes} minutes, {seconds:.0f} seconds: {file_name}")

