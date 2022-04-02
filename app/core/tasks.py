from celery.utils.log import get_task_logger
from datetime import datetime

from app import celery
from app.dl.helpers import seconds_to_time
# from app.serve.db import session_scope
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

    from app.serve.db import Video, session_scope
    with session_scope() as db_session:
        video = db_session.query(Video).filter_by(video_id=video_id).first()
        if not video:
            return False
        video.status = status

        db_session.add(video)
        db_session.commit()
    return True


@celery.task(name="core.tasks.gen_thumbnail", soft_time_limit=300, time_limit=360)
def gen_thumbnail_task(video_path: str, target_path: str):
    dur = time.time()
    log.info("Generating thumbnail...")


@celery.task(name="core.tasks.download", soft_time_limit=7200, time_limit=10800)    #, base=SQLAlchemyTask)
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
        index_video_data(video)
        log.info(f"Download complete in {minutes} minutes, {seconds:.0f} seconds: {file_name}")
    else:
        log.error(f"Download failed after {minutes} minutes, {seconds:.0f} seconds: {file_name}")
