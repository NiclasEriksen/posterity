from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, Float, Boolean
from sqlalchemy.orm import relationship, sessionmaker, scoped_session
from sqlalchemy.ext.declarative import declarative_base
from flask_login import UserMixin
import os
import json
from datetime import datetime
import time
import logging


engine = create_engine('sqlite:///db.sqlite3')
db_session = scoped_session(sessionmaker(bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()

log = logging.getLogger("klippekort.download")
AUTH_LEVEL_USER = 0
AUTH_LEVEL_MOD = 1
AUTH_LEVEL_ADMIN = 2


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
    duration = Column(Float)
    source = Column(String)
    location = Column(String)
    safe_to_store = Column(Boolean)
    verified = Column(Boolean)
    duplicate_of_id = Column(Integer, ForeignKey("videos.id"))
    duplicate_of = relationship("Video", remote_side=[id])
    duplicates = relationship("Video", back_populates="duplicate_of")

    @property
    def upload_time_str(self) -> str:
        return self.upload_time.strftime("%Y-%m-%d %H:%M:%S")

    def to_json(self) -> dict:
        return {
            "url": self.url,
            "source": self.source,
            "title": self.title,
            "video_title": self.orig_title,
            "content_warning": self.content_warning,
            "status": self.status,
            "format": self.video_format,
            "duration": self.duration,
            "location": self.location,
            "video_id": self.video_id,
            "safe_to_store": self.safe_to_store,
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
            self.video_format = d["format"]
        except KeyError:
            self.video_format = "Unknown"
        try:
            self.location = d["location"]
        except KeyError:
            self.location = "Unknown"
        try:
            self.verified = d["verified"]
        except KeyError:
            self.verified = False
        try:
            self.safe_to_store = d["safe_to_store"]
        except KeyError:
            self.safe_to_store = False
        try:
            self.upload_time = datetime.utcfromtimestamp(d["upload_time"])
        except KeyError:
            pass
        try:
            self.video_id = d["video_id"]
        except KeyError:
            log.error("No video id given for json, I hope this gets set manually...")
            pass


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


def init_db():
    # Booooom
    Base.metadata.create_all(bind=engine)


if __name__ == "__main__":
    init_db()

