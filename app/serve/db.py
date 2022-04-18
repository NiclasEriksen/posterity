import os
import json
from datetime import datetime, timedelta
import time
import shortuuid
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, Float, Boolean, Table
from sqlalchemy.orm import relationship, sessionmaker, scoped_session
from sqlalchemy.ext.declarative import declarative_base
from flask_login import UserMixin
from contextlib import contextmanager
from werkzeug.local import LocalProxy
from flask import current_app
from app.dl.helpers import seconds_to_verbose_time, seconds_to_hhmmss, convert_file_size, make_stub
from app.dl import STATUS_DOWNLOADING, STATUS_PROCESSING, STATUS_INVALID,\
    STATUS_FAILED, STATUS_COMPLETED, STATUS_PENDING, STATUS_COOKIES, STATUS_STRINGS,\
    MAX_BIT_RATE_PER_PIXEL, MIN_BIT_RATE_PER_PIXEL
from app.dl.metadata import get_source_site


log = LocalProxy(lambda: current_app.logger)
# log = logging.getLogger("posterity.db")

DB_URL = os.environ.get("POSTERITY_DB", "")

engine = create_engine(DB_URL, pool_pre_ping=True)
db_session = scoped_session(sessionmaker(bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()

# log = logging.getLogger("posterity.download")
AUTH_LEVEL_USER = 0
AUTH_LEVEL_EDITOR = 1
AUTH_LEVEL_ADMIN = 2

TOKEN_BASE_LENGTH = 8
MAX_TOKEN_USES = 20

PROCESSING_RECOMMENDATION = 0.33

REASON_DUPLICATE        = 0
REASON_MISSING_TAGS     = 1
REASON_WRONG_TAGS       = 2
REASON_BROKEN           = 3
REASON_MISLEADING_TITLE = 4
REASON_BETTER_SOURCE    = 5
REASON_NO_RELEVANCE     = 6
REASON_PRIVACY          = 7
REASON_OTHER            = 8
REASON_TEXTS = {
    REASON_DUPLICATE        : "Duplicate video",
    REASON_MISSING_TAGS     : "Missing content tags",
    REASON_WRONG_TAGS       : "Wrong content tags",
    REASON_BROKEN           : "Broken video",
    REASON_MISLEADING_TITLE : "Misleading title",
    REASON_BETTER_SOURCE    : "Have a better source link",
    REASON_NO_RELEVANCE     : "Video is not relevant",
    REASON_PRIVACY          : "Incrimination/Doxxing/Privacy",
    REASON_OTHER            : "Other reasons"
}


tag_association_table = Table(
    "tag_association", Base.metadata,
    Column("video_id", ForeignKey("videos.id")),
    Column("tag_id", ForeignKey("content_tags.id"))
)
tag_deleted_association_table = Table(
    "tag_deleted_association", Base.metadata,
    Column("video_id", ForeignKey("deleted_videos.id")),
    Column("tag_id", ForeignKey("content_tags.id"))
)

category_association_table = Table(
    "category_association", Base.metadata,
    Column("video_id", ForeignKey("videos.id")),
    Column("category_id", ForeignKey("categories.id"))
)
category_deleted_association_table = Table(
    "category_deleted_association", Base.metadata,
    Column("video_id", ForeignKey("deleted_videos.id")),
    Column("category_id", ForeignKey("categories.id"))
)

false_positive_association_table = Table(
    "false_positive_association", Base.metadata,
    Column("left_id", ForeignKey('videos.id'), primary_key=True),
    Column("right_id", ForeignKey('videos.id'), primary_key=True)
)


@contextmanager
def session_scope():
    session = db_session
    try:
        yield session
        session.commit()
    except:
        session.rollback()
        raise
    finally:
        session.close()


class User(UserMixin, Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(32), unique=True)
    password = Column(String(256))
    auth_level = Column(Integer)
    autoplay_videos = Column(Boolean)

    def check_auth(self, level: int) -> bool:
        return self.auth_level >= level

    @property
    def is_editor(self) -> bool:
        return self.check_auth(AUTH_LEVEL_EDITOR)


class Video(Base):
    __tablename__ = "videos"

    id = Column(Integer, primary_key=True)
    video_id = Column(String, unique=True)
    title = Column(String, default="")
    orig_title = Column(String, default="")
    url = Column(String, default="")
    theatre_id = Column(Integer, ForeignKey("theatres.id"))
    theatre = relationship("Theatre", back_populates="videos")
    status = Column(Integer)
    upload_time = Column(DateTime)
    orig_upload_time = Column(DateTime)
    video_format = Column(String, default="")
    audio_format = Column(String, default="")
    processed_video_format = Column(String, default="")
    processed_audio_format = Column(String, default="")
    width = Column(Integer, default=0)
    height = Column(Integer, default=0)
    bit_rate = Column(Integer, default=0)
    processed_bit_rate = Column(Integer, default=0)
    frame_rate = Column(Float, default=0.0)
    processed_frame_rate = Column(Float, default=0.0)
    file_size = Column(Float, default=0.0)
    processed_file_size = Column(Float, default=0.0)
    duration = Column(Float, default=0.0)
    source = Column(String, default="")
    location = Column(String, default="")
    verified = Column(Boolean, default=False)
    post_processed = Column(Boolean, default=False)
    task_id = Column(String, default="")
    pid = Column(Integer, default=-1)
    private = Column(Boolean, default=False)
    user_reports = relationship("UserReport", back_populates="video")
    duplicates = relationship(
        "Video", lambda: video_duplicates,
        primaryjoin=lambda: Video.id == video_duplicates.c.video_id,
        secondaryjoin=lambda: Video.id == video_duplicates.c.duplicate_id,
        backref="duplicate_of"
    )
    false_positives = relationship(
        "Video", secondary=false_positive_association_table,
        primaryjoin=id==false_positive_association_table.c.left_id,
        secondaryjoin=id==false_positive_association_table.c.right_id,
        backref="false_positives_left"
    )
    tags = relationship("ContentTag", secondary=tag_association_table)
    categories = relationship("Category", secondary=category_association_table)

    def __init__(self):
        self.upload_time = datetime.now()

    @property
    def page_url(self) -> str:
        return f"https://posterity.no/{self.video_id}"

    def user_can_edit(self, user: User) -> bool:
        if user.check_auth(AUTH_LEVEL_EDITOR):
            return True
        elif user.is_authenticated and user.username == self.source:
            return True
        return False

    def user_can_see(self, user: User) -> bool:
        if self.ready_to_play and not self.private and self.verified:
            return True
        elif user.check_auth(AUTH_LEVEL_USER) and self.ready_to_play and not self.private:
            return True
        if user.check_auth(AUTH_LEVEL_EDITOR):
            return True
        elif user.check_auth(AUTH_LEVEL_USER) and user.username == self.source and user.username != "Anonymous":
            return True
        return False


    @property
    def has_duplicates(self) -> bool:
        if not len(self.duplicates):
            return False
        for v in self.duplicates:
            if v not in self.false_positives:
                return True
        return False

    @property
    def duplicate_count(self):
        c = 0
        for v in self.duplicates:
            if v not in self.false_positives:
                c += 1
        return c

    @property
    def pending_duplicates(self):
        return [v for v in self.duplicates if v not in self.false_positives]

    @property
    def content_warning(self):
        return " ".join(t.name for t in self.tags_by_category)

    @property
    def ready_to_play(self) -> bool:
        return self.status == STATUS_COMPLETED

    @property
    def can_be_changed(self) -> bool:
        return self.status not in [STATUS_DOWNLOADING, STATUS_PROCESSING]

    @property
    def recommend_post_process(self) -> bool:
        if self.post_processed or not self.ready_to_play or not self.bit_rate:
            return False
        elif self.bit_rate < 320000 and self.duration < 300:
            return False
        elif self.bit_rate < 250000 and self.duration >= 300:
            return False

        pixels = self.width * self.height * (self.frame_rate / 30.0)
        min_bit_rate = pixels * MIN_BIT_RATE_PER_PIXEL
        max_bit_rate = pixels * MAX_BIT_RATE_PER_PIXEL
        r = max_bit_rate - min_bit_rate
        br = min(1.0, max(0.0, self.bit_rate - min_bit_rate) / r)

        return br >= PROCESSING_RECOMMENDATION

    @property
    def status_str(self) -> str:
        if self.status in STATUS_STRINGS:
            return STATUS_STRINGS[self.status]
        return str(f"Status {self.status}")

    @property
    def source_site_name(self) -> str:
        s = get_source_site(self.url)
        if len(s):
            return s
        return "world"

    @property
    def upload_time_str(self) -> str:
        return self.upload_time.strftime("%b %d, %H:%M").lower()

    @property
    def upload_time_iso8601(self) -> str:
        if self.upload_time:
            return self.upload_time.isoformat()
        return "Unknown date."

    @property
    def upload_time_elapsed(self) -> int:
        if self.upload_time:
            return round((datetime.now() - self.upload_time).total_seconds())
        return 0

    @property
    def upload_time_verbose(self) -> str:
        s = self.upload_time_elapsed
        if s >= 86400:  # 24 hours
            return self.upload_time_str
        if s >= 5400:
            return f"{round(s / 3600)} hours ago"
        elif s >= 3600:
            return "1 hour ago"
        elif s >= 90:
            return f"{round(s / 60)} minutes ago"
        elif s >= 60:
            return "1 minute ago"
        return f"{seconds_to_verbose_time(s)} ago"

    @property
    def orig_upload_time_str(self) -> str:
        return self.orig_upload_time.strftime("%b %d").lower()

    @property
    def upload_time_elapsed_verbose(self) -> str:
        s = self.upload_time_elapsed
        if s >= 86400:  # 24 hours
            return self.upload_time_str
        return f"{self.upload_time_verbose}, {self.upload_time_str}"

    @property
    def duration_seconds(self) -> int:
        try:
            return round(self.duration)
        except (TypeError, ValueError):
            return 0

    @property
    def duration_str(self) -> str:
        return seconds_to_hhmmss(self.duration)

    @property
    def duration_str_verbose(self) -> str:
        return seconds_to_verbose_time(self.duration)

    @property
    def tags_by_category(self) -> list:
        return sorted(self.tags, key=lambda x: x.category, reverse=True)

    @property
    def content_tags_string(self) -> str:
        return "/".join([t.name for t in self.tags_by_category])

    @property
    def content_tags_readable(self) -> str:
        return ", ".join([t.name for t in self.tags_by_category])

    def content_tags_readable_priority(self, priority: int) -> str:
        return ", ".join([t.name for t in self.tags_by_category if t.category >= priority])

    @property
    def format_str(self) -> str:
        if self.video_format and self.audio_format:
            return f"{self.video_format} / {self.audio_format}"
        return f"{self.video_format} / {self.audio_format}" if self.audio_format else str(self.video_format)

    @property
    def bit_rate_str(self) -> str:
        try:
            kbps = self.bit_rate / 1000
        except (TypeError, ValueError):
            kbps = 0.0
        return f"{kbps:.1f} kbit/s"

    @property
    def processed_bit_rate_str(self) -> str:
        try:
            kbps = self.processed_bit_rate / 1000
        except (TypeError, ValueError):
            kbps = 0.0
        return f"{kbps:.1f} kbit/s"

    @property
    def frame_rate_str(self) -> str:
        try:
            fr = int(self.frame_rate)
        except (TypeError, ValueError):
            fr = 0
        return f"{fr} FPS"

    @property
    def processed_frame_rate_str(self) -> str:
        try:
            fr = int(self.processed_frame_rate)
        except (TypeError, ValueError):
            fr = 0
        return f"{fr} FPS"

    @property
    def dimensions_str(self) -> str:
        if self.width and self.height:
            return f"{self.width}x{self.height}"
        return "No size"

    @property
    def aspect_ratio(self) -> float:
        if self.width and self.height:
            return self.width / self.height
        return 0.0

    @property
    def preview_width(self) -> int:
        if self.width and self.height:
            ratio = self.width / self.height
            return int(min(640, 360 * ratio))
        return 0

    @property
    def preview_height(self) -> int:
        if self.width and self.height:
            ratio = self.height / self.width
            return int(min(360, 640 * ratio))
        return 0

    @property
    def player_width(self) -> int:
        return int(self.preview_width * 2)

    @property
    def player_height(self) -> int:
        return int(self.preview_height * 2)

    @property
    def file_size_str(self) -> str:
        if self.file_size:
            return convert_file_size(self.file_size)
        return "?B"

    @property
    def processed_file_size_str(self) -> str:
        if self.processed_file_size:
            return convert_file_size(self.processed_file_size)
        return "?B"

    def to_json(self) -> dict:
        return {
            "url": self.url,
            "source": self.source,
            "title": self.title,
            "video_title": self.orig_title,
            "content_warning": self.content_tags_string,
            "tags": [t.id for t in self.tags_by_category],
            "categories": [c.id for c in self.categories],
            "category": "/".join([c.name for c in self.categories]),
            "status": self.status,
            "format": f"{self.video_format} / {self.audio_format}",
            "processed_format": f"{self.processed_video_format} / {self.processed_audio_format}",
            "width": self.width if self.width else 0,
            "theatre": self.theatre.stub if self.theatre else "",
            "height": self.height if self.height else 0,
            "bit_rate": self.bit_rate if self.bit_rate else 0,
            "frame_rate": self.frame_rate if self.frame_rate else 0.0,
            "file_size": self.file_size if self.file_size else 0,
            "processed_bit_rate": self.processed_bit_rate if self.processed_bit_rate else 0,
            "processed_frame_rate": self.processed_frame_rate if self.processed_frame_rate else 0.0,
            "processed_file_size": self.processed_file_size if self.processed_file_size else 0,
            "duration": self.duration,
            "location": self.location,
            "private": self.private,
            "video_id": self.video_id,
            "verified": self.verified,
            "upload_time": time.mktime(self.upload_time.timetuple()) if self.upload_time else 0,
            "orig_upload_time": time.mktime(self.orig_upload_time.timetuple()) if self.orig_upload_time else 0,
            "duplicate": ", ".join(v.video_id for v in self.duplicates),
        }
    
    def from_json(self, d: dict):
        try:
            self.url = d["url"]
        except KeyError:
            pass
        try:
            theatre = db_session.query(Theatre).filter_by(stub=d["theatre"]).first()
            if theatre and not theatre == self.theatre:
                self.theatre = theatre
        except KeyError:
            pass
        try:
            self.task_id = d["task_id"]
        except KeyError:
            pass
        try:
            self.pid = int(d["pid"])
        except (KeyError, TypeError, ValueError):
            pass
        try:
            self.title = d["title"]
        except KeyError:
            pass
        try:
            self.orig_title = d["video_title"]
        except KeyError:
            pass
        try:
            self.duration = d["duration"]
        except KeyError:
            pass
        try:
            self.status = d["status"]
        except KeyError:
            pass
        try:
            self.source = d["source"]
        except KeyError:
            pass
        try:
            formats = d["format"].split(" / ")
            self.video_format = formats[0]
            if len(formats) > 1:
                self.audio_format = formats[1]
        except (KeyError, IndexError, AttributeError):
            self.video_format = "Unknown"
            self.audio_format = "Unknown"
        try:
            formats = d["processed_format"].split(" / ")
            self.processed_video_format = formats[0]
            if len(formats) > 1:
                self.processed_audio_format = formats[1]
        except (KeyError, IndexError, AttributeError):
            self.processed_video_format = "Unknown"
            self.processed_audio_format = "Unknown"
        try:
            self.location = d["location"]
        except KeyError:
            self.location = "Unknown"
        try:
            self.verified = d["verified"]
        except KeyError:
            self.verified = False
        try:
            self.private = d["private"]
        except KeyError:
            pass
        try:
            self.width = d["width"]
        except KeyError:
            self.width = 0
        try:
            self.height = d["height"]
        except KeyError:
            self.height = 0
        try:
            self.bit_rate = d["bit_rate"]
        except KeyError:
            self.bit_rate = 0
        try:
            self.frame_rate = d["frame_rate"]
        except KeyError:
            self.frame_rate = 0.0
        try:
            self.file_size = d["file_size"]
        except KeyError:
            self.file_size = 0
        try:
            self.processed_file_size = d["processed_file_size"]
        except KeyError:
            self.processed_file_size = 0
        try:
            self.processed_frame_rate = d["processed_frame_rate"]
        except KeyError:
            self.processed_frame_rate = 0.0
        try:
            self.processed_bit_rate = d["processed_bit_rate"]
        except KeyError:
            self.processed_bit_rate = 0.0
        try:
            self.upload_time = datetime.utcfromtimestamp(d["upload_time"])
        except KeyError:
            pass
        try:
            ot = d["orig_upload_time"]
            if isinstance(ot, datetime):
                self.orig_upload_time = ot
            elif isinstance(ot, str) or isinstance(ot, int) or isinstance(ot, float):
                self.orig_upload_time = datetime.utcfromtimestamp(ot)
        except KeyError:
            pass
        try:
            self.video_id = d["video_id"]
        except KeyError:
            log.error("No video id given for json, I hope this gets set manually...")
            pass
        try:
            tags = d["tags"]
        except KeyError:
            pass
        else:
            for t in tags:
                try:
                    ct = ContentTag.query.filter_by(id=int(t)).first()
                except (TypeError, ValueError):
                    pass
                else:
                    if ct and ct not in self.tags:
                        self.tags.append(ct)
        try:
            if "/" in d["content_warning"]:
                cw = d["content_warning"].split("/")
            else:
                cw = [d["content_warning"]]
        except KeyError:
            pass
        else:
            for c in cw:
                tag = ContentTag.query.filter_by(name=c.lstrip().rstrip().capitalize()).first()
                if not tag:
                    tag = ContentTag.query.filter_by(name=c.lstrip().rstrip()).first()
                    if not tag:
                        try:
                            int(c)
                        except (TypeError, ValueError):
                            pass
                        else:
                            tag = ContentTag.query.filter_by(id=int(c)).first()

                if tag and tag not in self.tags:
                    self.tags.append(tag)

        try:
            categories = d["categories"]
        except KeyError:
            pass
        else:
            for c in categories:
                try:
                    ct = Category.query.filter_by(id=int(c)).first()
                except (TypeError, ValueError):
                    pass
                else:
                    if ct and ct not in self.categories:
                        self.categories.append(ct)
        try:
            if "/" in d["category"]:
                c = d["category"].split("/")
            else:
                c = [d["category"]]
        except KeyError:
            pass
        else:
            for ct in c:
                tag = Category.query.filter_by(name=ct.lstrip().rstrip().capitalize()).first()
                if not tag:
                    tag = Category.query.filter_by(name=ct.lstrip().rstrip()).first()
                    if not tag:
                        try:
                            int(ct)
                        except (TypeError, ValueError):
                            pass
                        else:
                            tag = Category.query.filter_by(id=int(ct)).first()

                if tag and tag not in self.categories:
                    self.categories.append(tag)


video_duplicates = Table(
    "video_duplicates", Base.metadata,
    Column("video_id", Integer, ForeignKey(Video.id), primary_key=True),
    Column("duplicate_id", Integer, ForeignKey(Video.id), primary_key=True)
)


class Theatre(Base):
    __tablename__ = "theatres"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True)
    stub = Column(String, unique=True)
    location = Column(String, default="Unknown")
    from_time = Column(DateTime)
    to_time = Column(DateTime)
    ongoing = Column(Boolean, default=True)
    logo_name = Column(String, default="no_logo.jpg")
    videos = relationship("Video", back_populates="theatre")


class RegisterToken(Base):
    __tablename__ = "tokens"
    id = Column(Integer, primary_key=True)
    name = Column(String)
    token = Column(String, unique=True)
    expires = Column(DateTime)
    uses = Column(Integer, default=0)
    auth_level = Column(Integer, default=0)

    def __init__(self, name: str, expires=None, uses: int = 0, auth_level: int = 0):
        self.name = name
        self.uses = uses
        self.auth_level = auth_level
        if not expires or not isinstance(expires, datetime):
            self.expires = datetime.now() + timedelta(days=30)
        else:
            self.expires = expires

    def generate(self):
        self.token = shortuuid.ShortUUID().random(
            length=TOKEN_BASE_LENGTH + (self.auth_level * TOKEN_BASE_LENGTH)
        )

    def spend_token(self) -> bool:
        if self.uses > 0:
            self.uses -= 1
            return True
        else:
            log.info("No more tokens to spend!")
            return False

    def is_valid(self) -> bool:
        return self.expires >= datetime.now() and self.uses > 0


class ContentTag(Base):
    __tablename__ = "content_tags"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True)
    stub = Column(String, unique=True)
    category = Column(Integer, default=0)
    censor = Column(Boolean)

    def __init__(self, name: str):
        self.name = name
        self.stub = make_stub(name)
        self.censor = False
        self.category = 0


class Category(Base):
    __tablename__ = "categories"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True)
    stub = Column(String, unique=True)

    def __init__(self, name: str):
        self.name = name
        self.stub = make_stub(name)


class UserReport(Base):
    __tablename__ = "reports"
    id = Column(Integer, primary_key=True)
    video_db_id = Column(Integer, ForeignKey("videos.id"))
    video = relationship("Video", back_populates="user_reports")
    report_time = Column(DateTime, default=datetime.now())
    source = Column(String, default="Anonymous")
    text = Column(String, default="")
    reason = Column(Integer, default=REASON_OTHER)

    def __init__(self, video: Video, reason: int, text: str, source: str):
        self.video = video
        self.reason = reason
        self.text = text
        self.source = source
        self.report_time = datetime.now()

    @property
    def report_time_str(self) -> str:
        if self.report_time:
            return self.report_time.strftime("%b %d, %H:%M").lower()
        return "Unknown"

    @property
    def reason_str(self) -> str:
        try:
            return REASON_TEXTS[self.reason]
        except KeyError:
            return "Unknown reason"


class RejectedVideo(Base):
    __tablename__ = "rejected"
    id = Column(Integer, primary_key=True)
    url = Column(String)
    reason = Column(Integer)
    upload_time = Column(DateTime)
    reject_time = Column(DateTime)
    uploader = Column(String)
    title = Column(String)


class DeletedVideo(Base):
    __tablename__ = "deleted_videos"
    id = Column(Integer, primary_key=True)
    video_id = Column(String, unique=True)
    url = Column(String)
    upload_time = Column(DateTime)
    delete_time = Column(DateTime)
    deleted_by = Column(String, default="Unknown")
    title = Column(String, default="")
    orig_title = Column(String, default="")
    source = Column(String, default="Unknown")
    tags = relationship("ContentTag", secondary=tag_deleted_association_table)
    categories = relationship("Category", secondary=category_deleted_association_table)

    def __init__(self, video: Video, deleted_by="Unknown"):
        self.video_id = video.video_id
        self.url = video.url
        self.upload_time = video.upload_time
        self.title = video.title
        self.orig_title = video.orig_title
        self.source = video.source
        self.deleted_by = deleted_by
        self.delete_time = datetime.now()
        for t in video.tags:
            self.tags.append(t)
        for t in video.categories:
            self.categories.append(t)

    def restore(self) -> Video:
        v = Video()
        v.video_id = self.video_id
        v.title = self.title
        v.orig_title = self.orig_title
        v.source = self.source
        v.upload_time = self.upload_time
        v.url = self.url
        v.status = STATUS_COMPLETED
        v.verified = False
        for t in self.tags:
            v.tags.append(t)
        for t in self.categories:
            v.categories.append(t)
        return v


# To avoid circular imports of Video model
from .search import index_video_data, remove_videos_index


def index_all_videos_from_db():
    try:
        remove_videos_index()
    except Exception as e:
        log.error(e)
        return

    for video in Video.query.all():
        index_video_data(video)


def load_all_videos_from_disk(media_path: str):
    videos = []

    try:
        remove_videos_index()
    except Exception as e:
        log.debug(e)
        log.error("Unable to remove video index (unknown error)")

    for f in os.listdir(media_path):
        if f.endswith(".json"):
            video_id = f.split(".json")[0]
            existing = Video.query.filter_by(video_id=video_id).first()
            if existing:
                index_video_data(existing)
                continue

            try:
                with open(os.path.join(media_path, f)) as jf:
                    d = json.load(jf)

                    if "video_id" not in d.keys():
                        d["video_id"] = video_id
                    if not len(d["video_id"]):
                        d["video_id"] = video_id

                    video = Video()
                    video.from_json(d)
                    #
                    # if "duplicate" in d.keys():
                    #     if len(d["duplicate"]):
                    #         if d["duplicate"] in duplicates:
                    #             duplicates[d["duplicate"]].append(video_id)
                    #         else:
                    #             duplicates[d["duplicate"]] = [video_id]

                    videos.append(video)
                    index_video_data(video)

            except json.JSONDecodeError:
                log.error(f"{f.split('.json')[0]} seems broken, skipped.")
                continue

    db_session.add_all(videos)
    db_session.commit()
    #
    # # Connect duplicates
    # for original, dupes in duplicates.items():
    #     og = db_session.query(Video).filter_by(video_id=original).first()
    #     if not og:
    #         log.warning(f"Video lists {original} as original, but it doesn't exist!")
    #         continue
    #     for duplicate in dupes:
    #         d = db_session.query(Video).filter_by(video_id=duplicate).first()
    #         if not d:
    #             log.warning(f"Video {duplicate} listed as duplicate, but it doesn't exist!")
    #             continue
    #
    #         og.duplicates.append(d)
    #         d.duplicate_of = og
    #         db_session.add(d)
    #
    #     db_session.add(og)
    #
    # db_session.commit()

    log.info(f"Loaded {len(videos)} videos from json files.")

    # all_videos = session.query(Video).all()


def load_content_warning_as_tags(media_path: str):
    for video in Video.query.all():
        try:
            with open(os.path.join(media_path, video.video_id + ".json")) as jf:
                json_data = json.load(jf)
        except (OSError, FileNotFoundError):
            log.error(f"Problem finding json for {video.video_id}")
            continue

        if "content_warning" not in json_data:
            log.error(f"No content warning for {video.video_id}")
            continue

        if "/" in json_data["content_warning"]:
            cw = json_data["content_warning"].split("/")
        else:
            cw = [json_data["content_warning"]]

        for c in cw:
            tag = ContentTag.query.filter_by(name=c.lstrip().rstrip().capitalize()).first()
            if tag and tag not in video.tags:
                video.tags.append(tag)

        db_session.add(video)

    db_session.commit()


def init_db():
    # Booooom
    Base.metadata.create_all(bind=engine)


if __name__ == "__main__":
    init_db()

