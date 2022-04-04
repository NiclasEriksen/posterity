from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, Float, Boolean, Table
from sqlalchemy.orm import relationship, sessionmaker, scoped_session
from sqlalchemy.ext.declarative import declarative_base
from flask_login import UserMixin
import os
import json
from datetime import datetime, timedelta
import time
# import logging
from contextlib import contextmanager
from werkzeug.local import LocalProxy
from flask import current_app
from app.dl.helpers import seconds_to_verbose_time, seconds_to_hhmmss, convert_file_size


log = LocalProxy(lambda: current_app.logger)
# log = logging.getLogger("posterity.db")

DB_URL = os.environ.get("POSTERITY_DB", "")

engine = create_engine(DB_URL, pool_pre_ping=True)
db_session = scoped_session(sessionmaker(bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()

# log = logging.getLogger("posterity.download")
AUTH_LEVEL_USER = 0
AUTH_LEVEL_MOD = 1
AUTH_LEVEL_ADMIN = 2

tag_association_table = Table(
    "tag_association", Base.metadata,
    Column("video_id", ForeignKey("videos.id")),
    Column("tag_id", ForeignKey("content_tags.id"))
)

category_association_table = Table(
    "category_association", Base.metadata,
    Column("video_id", ForeignKey("videos.id")),
    Column("category_id", ForeignKey("categories.id"))
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


class Video(Base):
    __tablename__ = "videos"

    id = Column(Integer, primary_key=True)
    video_id = Column(String, unique=True)
    title = Column(String)
    orig_title = Column(String)
    url = Column(String)
    status = Column(Integer)
    content_warning = Column(String)
    upload_time = Column(DateTime)
    video_format = Column(String)
    audio_format = Column(String)
    width = Column(Integer, default=0)
    height = Column(Integer, default=0)
    bit_rate = Column(Integer, default=0)
    frame_rate = Column(Float, default=0.0)
    file_size = Column(Float, default=0.0)
    duration = Column(Float)
    source = Column(String)
    location = Column(String)
    verified = Column(Boolean)
    duplicate_of_id = Column(Integer, ForeignKey("videos.id"))
    duplicate_of = relationship("Video", remote_side=[id])
    duplicates = relationship("Video", back_populates="duplicate_of")
    tags = relationship("ContentTag", secondary=tag_association_table)
    categories = relationship("Category", secondary=category_association_table)

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
        return f"{seconds_to_verbose_time(s)} ago"

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
    def frame_rate_str(self) -> str:
        try:
            fr = int(self.frame_rate)
        except (TypeError, ValueError):
            fr = 0
        return f"{fr} FPS"

    @property
    def dimensions_str(self) -> str:
        if self.width and self.height:
            return f"{self.width}x{self.height}"
        return "No size"

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
            "width": self.width if self.width else 0,
            "height": self.height if self.height else 0,
            "bit_rate": self.bit_rate if self.bit_rate else 0,
            "frame_rate": self.frame_rate if self.frame_rate else 0.0,
            "file_size": self.file_size if self.file_size else 0,
            "duration": self.duration,
            "location": self.location,
            "video_id": self.video_id,
            "verified": self.verified,
            "upload_time": time.mktime(self.upload_time.timetuple()) if self.upload_time else 0,
            "duplicate": self.duplicate_of.video_id if self.duplicate_of else "",
        }
    
    def from_json(self, d: dict):
        self.url = d["url"]
        self.title = d["title"]
        self.orig_title = d["video_title"]
        self.duration = d["duration"]
        try:
            self.status = d["status"]
        except KeyError:
            self.status = 2
        try:
            self.source = d["source"]
        except KeyError:
            self.source = ""
        try:
            self.content_warning = d["content_warning"]
        except KeyError:
            self.content_warning = "Unknown"
        try:
            formats = d["format"].split(" / ")
            self.video_format = formats[0]
            if len(formats) > 1:
                self.audio_format = formats[1]
        except (KeyError, IndexError, AttributeError):
            self.video_format = "Unknown"
            self.audio_format = "Unknown"
        try:
            self.location = d["location"]
        except KeyError:
            self.location = "Unknown"
        try:
            self.verified = d["verified"]
        except KeyError:
            self.verified = False
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
            self.upload_time = datetime.utcfromtimestamp(d["upload_time"])
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
                if tag and tag not in self.categories:
                    self.categories.append(tag)


class RegisterToken(Base):
    __tablename__ = "tokens"
    id = Column(Integer, primary_key=True)
    name = Column(String)
    token = Column(String)
    expires = Column(DateTime)
    uses = Column(Integer)

    def spend_token(self) -> bool:
        if self.uses > 0:
            self.uses -= 1
            return True
        else:
            log.info("No more tokens to spend!")
            return False

    def check(self, other: str) -> bool:
        return other.strip() == self.token.strip()


class ContentTag(Base):
    __tablename__ = "content_tags"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True)
    category = Column(Integer, default=0)
    censor = Column(Boolean)

    def __init__(self, name: str):
        self.name = name
        self.censor = False
        self.category = 0


class Category(Base):
    __tablename__ = "categories"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True)

    def __init__(self, name: str):
        self.name = name


class FailedDownload(Base):
    __tablename__ = "failed"
    id = Column(Integer, primary_key=True)
    url = Column(String)
    reason = Column(Integer)
    upload_time = Column(DateTime)
    source = Column(String)
    title = Column(String)
    content_warning = Column(String)


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
    duplicates = {}
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

                    if "duplicate" in d.keys():
                        if len(d["duplicate"]):
                            if d["duplicate"] in duplicates:
                                duplicates[d["duplicate"]].append(video_id)
                            else:
                                duplicates[d["duplicate"]] = [video_id]

                    videos.append(video)
                    index_video_data(video)

            except json.JSONDecodeError:
                log.error(f"{f.split('.json')[0]} seems broken, skipped.")
                continue

    db_session.add_all(videos)
    db_session.commit()

    # Connect duplicates
    for original, dupes in duplicates.items():
        og = db_session.query(Video).filter_by(video_id=original).first()
        if not og:
            log.warning(f"Video lists {original} as original, but it doesn't exist!")
            continue
        for duplicate in dupes:
            d = db_session.query(Video).filter_by(video_id=duplicate).first()
            if not d:
                log.warning(f"Video {duplicate} listed as duplicate, but it doesn't exist!")
                continue

            og.duplicates.append(d)
            d.duplicate_of = og
            db_session.add(d)

        db_session.add(og)

    db_session.commit()

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

