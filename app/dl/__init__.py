import os
import logging
from logging.handlers import RotatingFileHandler
from flask import current_app
from .helpers import resource_path

#Logging
log = logging.getLogger("posterity_dl")
log.setLevel(logging.DEBUG)

formatter = logging.Formatter(
    "%(levelname)s|%(asctime)s|%(name)s| %(message)s",
    "%Y-%m-%d %H:%M:%S"
)
log_path = resource_path(os.path.join("log", "posterity_dl.log"))

log_handler = RotatingFileHandler(log_path, maxBytes=8*1024*1024, backupCount=0, encoding="utf-8")
log_handler.setLevel(logging.DEBUG)
log_handler.setFormatter(formatter)

stream_handler = logging.StreamHandler()
stream_handler.setLevel(logging.INFO)
stream_handler.setFormatter(formatter)

log.addHandler(log_handler)
log.addHandler(stream_handler)
