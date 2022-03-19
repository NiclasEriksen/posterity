from celery.utils.log import get_task_logger

from app import celery
from app.dl.dl import download_from_json_data

logger = get_task_logger(__name__)


@celery.task(name='core.tasks.test',
             soft_time_limit=60, time_limit=65)
def test_task():
    logger.info('running test task')
    return True


@celery.task(name="core.tasks.download", soft_time_limit=5400, time_limit=7200)
def download_task(data: dict, file_name: str):
    import time
    logger.info("Starting download.")
    success = download_from_json_data(data, file_name)
    if success:
        logger.info("Download complete.")
    else:
        logger.error("Download failed.")
