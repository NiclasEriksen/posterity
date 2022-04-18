import os
import logging
from logging.handlers import RotatingFileHandler
from flask import current_app
from .helpers import resource_path
from dotenv import load_dotenv

load_dotenv()

STATUS_DOWNLOADING = 0
STATUS_COMPLETED = 1
STATUS_FAILED = 2
STATUS_INVALID = 3
STATUS_COOKIES = 4
STATUS_PENDING = 5
STATUS_PROCESSING = 6
STATUS_CHECKING = 7

STATUS_STRINGS = {
    STATUS_DOWNLOADING: "downloading",
    STATUS_COMPLETED: "completed",
    STATUS_FAILED: "failed",
    STATUS_INVALID: "invalid",
    STATUS_COOKIES: "cookies",
    STATUS_PENDING: "pending",
    STATUS_PROCESSING: "processing",
    STATUS_CHECKING: "checking"
}

CRF = 26
CRF_LOW = 34
MAX_DURATION_HD: float = 10 * 60.0
MAX_RESOLUTION_MD: int = 720
MAX_DURATION_MD: float = 45 * 60.0
MAX_RESOLUTION_SD: int = 480
MAX_DURATION_SD: float = 480 * 60.0     # 8 hours maximum.
MIN_BIT_RATE_PER_PIXEL = 0.75
MAX_BIT_RATE_PER_PIXEL = 2.7
MAX_AUD_BIT_RATE = 128
MAX_FPS = 60
SPLIT_FPS_THRESHOLD = 40.0

TEXT_MARGIN = 12
TEXT_PADDING = 8
STROKE_SMALL = 1
STROKE_MEDIUM = 2
STROKE_LARGE = 3
FONT_SIZE_SMALL = 24
FONT_SIZE_MEDIUM = 32
FONT_SIZE_LARGE = 42
FONT_COLOR = (192, 192, 192)
GRAPHIC_COLOR = (225, 96, 112)
EMOTIONAL_COLOR = (239, 198, 99)
FONT_GS = 128
GRAPHIC_GS = 0
EMOTIONAL_GS = 64
FONT_STROKE_COLOR = (32, 32, 32)
GRAPHIC_STROKE_COLOR = (32, 32, 32)
EMOTIONAL_STROKE_COLOR = (32, 32, 32)
FONT_STROKE_GS = 255
GRAPHIC_STROKE_GS = 255
EMOTIONAL_STROKE_GS = 192


media_path = os.environ.get("MEDIA_FOLDER", "")
original_path = os.path.join(media_path, "original")
processed_path = os.path.join(media_path, "processed")
tmp_path = os.path.join(media_path, "tmp")
json_path = media_path

thumbnail_path = os.environ.get("THUMBNAIL_FOLDER", "")
preview_path = os.environ.get("PREVIEW_FOLDER", "")
upload_path = os.environ.get("UPLOAD_FOLDER", "")

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
