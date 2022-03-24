from celery.utils.log import get_task_logger
from datetime import datetime

from app import celery
from app.dl.dl import download_from_json_data
from app.dl.helpers import seconds_to_time
import time


logger = get_task_logger(__name__)


@celery.task(name="core.tasks.gen_thumbnail", soft_time_limit=300, time_limit=360)
def gen_thumbnail_task(video_path: str, target_path: str):
    dur = time.time()
    logger.info("Generating thumbnail...")


@celery.task(name="core.tasks.download", soft_time_limit=7200, time_limit=10800)
def download_task(data: dict, file_name: str):
    dur = time.time()
    logger.info("Starting download of " + str(file_name))
    try:
        success = download_from_json_data(data, file_name)
    except Exception as e:
        logger.error(e)
        success = False
    dur = time.time() - dur
    _hours, minutes, seconds = seconds_to_time(dur)
    if success:
        logger.info(f"Download complete in {minutes} minutes, {seconds:.0f} seconds: {file_name}")
    else:
        # try:
        #     fd = FailedDownload()
        #     fd.url = data["url"]
        #     fd.upload_time = datetime.now()
        #     fd.title = data["title"]
        #     fd.source = data["source"]
        #     db_session.add(fd)
        #     db_session.commit()
        # except Exception as e:
        #     db_session.rollback()
        #     logger.error(e)
        #     logger.error("FailedDownload not written to database.")

        logger.error(f"Download failed after {minutes} minutes, {seconds:.0f} seconds: {file_name}")
