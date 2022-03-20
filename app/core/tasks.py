from celery.utils.log import get_task_logger

from app import celery
from app.dl.dl import download_from_json_data
from app.dl.helpers import seconds_to_time

logger = get_task_logger(__name__)


@celery.task(name='core.tasks.test',
             soft_time_limit=60, time_limit=65)
def test_task():
    logger.info('running test task')
    return True


@celery.task(name="core.tasks.download", soft_time_limit=5400, time_limit=7200)
def download_task(data: dict, file_name: str):
    import time
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
        logger.error(f"Download failed after {minutes} minutes, {seconds:.0f} seconds: {file_name}")
