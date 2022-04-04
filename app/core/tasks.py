import os.path

from celery.utils.log import get_task_logger
from datetime import datetime

from app import celery
from app.dl.helpers import seconds_to_time
import time


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


@celery.task(name="core.tasks.gen_thumbnail", soft_time_limit=300, time_limit=360)
def gen_images_task(metadata: dict):
    from app.dl.metadata import generate_video_images
    from app.dl.dl import media_path, thumbnail_path, preview_path
    dur = time.time()
    log.info("Generating thumbnail...")

    try:
        video_id = metadata["video_id"]
        duration = metadata["duration"]
        content_warning = metadata["content_warning"]
    except KeyError:
        log.error("Missing data... cant do shit.")
        return

    vid_save_path = os.path.join(media_path, video_id + ".mp4")
    if not os.path.isfile(vid_save_path):
        log.error("No video file to generate images for.")
        return

    generate_video_images(
        vid_save_path,
        os.path.join(thumbnail_path, video_id + "_thumb.png"),
        os.path.join(preview_path, video_id + "_preview.png"),
        os.path.join(thumbnail_path, video_id + "_thumb_blurred.png"),
        os.path.join(preview_path, video_id + "_preview_blurred.png"),
        start=5 if duration >= 10.0 else 0,
        blur_amount=0.75,
        desaturate=True,
        content_text=content_warning if content_warning.lower().strip() != "none" else ""
    )
    dur = time.time() - dur
    _hours, minutes, seconds = seconds_to_time(dur)
    log.info(f"Images generated in {minutes} minutes, {seconds:.2f} seconds: {video_id}")


@celery.task(name="core.tasks.download", soft_time_limit=14400, time_limit=14700)    #, base=SQLAlchemyTask)
def download_task(data: dict, file_name: str):
    from app.serve.search import index_video_data
    from app.dl.dl import (
        download_from_json_data,
        find_duplicate_video_by_url,
        STATUS_DOWNLOADING,
        STATUS_COMPLETED,
        STATUS_FAILED,
        STATUS_INVALID,
        STATUS_COOKIES
    )

    if "video_id" not in data:
        log.error("Bad metadata to download from, aborting task.")
        return

    dur = time.time()
    log.info("Starting download of " + str(file_name))
    success = False
    try:
        for status in download_from_json_data(data, file_name):
            if status == STATUS_DOWNLOADING:
                log.info("Starting ffmpeg process...")
                update_video(file_name, STATUS_DOWNLOADING)
                continue
            elif status == STATUS_COMPLETED:
                log.info("Download function has completed with no errors.")
                success = True
            elif status in [STATUS_FAILED, STATUS_INVALID, STATUS_COOKIES]:
                log.info("Download function has failed.")
                if status == STATUS_FAILED:
                    log.error("Failure or exception during download.")
                elif status == STATUS_INVALID:
                    log.error("No video on that URL or unhandled formats.")
                elif status == STATUS_COOKIES:
                    log.error("That video needs cookies for geo-locked or age restricted content.")
            elif isinstance(status, dict):  # We got metadata back, heck yeah
                update_video(file_name, STATUS_COMPLETED, data=status)
                success = True
                break

            update_video(file_name, status)
            break   # Break on any yield that's not continued above

    except Exception as e:
        log.error(e)

    dur = time.time() - dur
    _hours, minutes, seconds = seconds_to_time(dur)
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

        log.error(f"Download failed after {minutes} minutes, {seconds:.0f} seconds: {file_name}")
