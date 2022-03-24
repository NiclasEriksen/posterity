import logging
import json
import os
import subprocess
from datetime import datetime
from typing import Union
from .helpers import seconds_to_time, resource_path, unique_filename
from .youtube import valid_youtube_url, get_content_info, AgeRestrictedError
from app import celery

log = logging.getLogger("posterity.download")
if celery:
    inspector = celery.control.inspect()

media_path = os.environ.get("MEDIA_FOLDER", "")
url_file_path = os.path.join(media_path, "urls.store")
STATUS_DOWNLOADING = 0
STATUS_COMPLETED = 1
STATUS_FAILED = 2
STATUS_INVALID = 3
STATUS_COOKIES = 4


if not os.path.isfile(url_file_path):
    open(url_file_path, "a").close()


def write_metadata_to_db(video_id: str, md: dict):
    from app.serve.db import db_session, Video
    try:
        existing = db_session.query(Video).filter_by(video_id=video_id).first()
    except Exception as e:
        db_session.rollback()
        log.error(e)
        existing = None

    if existing:
        video = existing
    else:
        video = Video()

    video.from_json(md)

    try:
        db_session.add(video)
        db_session.commit()
    except Exception as e:
        db_session.rollback()
        log.error(e)
        log.error(f"Unable to write video {video_id} to database.")


def write_metadata(video_id: str, md: dict):
    json_save_path = os.path.join(media_path, video_id + ".json")
    try:
        with open(json_save_path, "w") as json_file:
            json.dump(md, json_file)
    except OSError as e:
        log.error(e)
        log.error(f"JSON for {video_id} was not written to disk.")
    write_metadata_to_db(video_id, md)


def download_from_json_data(data: dict, file_name: str) -> bool:
    from app.serve.db import Video
    vid_save_path = os.path.join(media_path, file_name + ".mp4")

    metadata = {
        "url": "",
        "source": "",
        "title": "",
        "video_title": "",
        "content_warning": "",
        "format": "",
        "duration": 0,
        "upload_time": datetime.now().timestamp(),
        "safe_to_store": False,
        "status": STATUS_DOWNLOADING,
        "video_id": file_name,
        "verified": False,
    }
    try:
        metadata["url"] = data["url"]
        metadata["title"] = data["title"]
        metadata["source"] = data["source"]
        metadata["content_warning"] = data["content_warning"]
    except KeyError:
        log.error("Corrupted data?!")
        metadata["status"] = STATUS_INVALID
        write_metadata(file_name, metadata)
        return False

    if not valid_youtube_url(metadata["url"]):
        log.error("Invalid video url...")
        metadata["status"] = STATUS_INVALID
        write_metadata(file_name, metadata)
        return False
    elif media_path == "":
        log.error("No path to save video (MEDIA_FOLDER)...")
        metadata["status"] = STATUS_FAILED
        write_metadata(file_name, metadata)
        return False

    try:
        with open(url_file_path, "r") as url_file:
            existing_urls = url_file.read().splitlines()
    except OSError as e:
        log.error(e)
        log.error("Not getting URLs from disk.")
        existing_urls = []

    if metadata["url"] in existing_urls:
        log.info("This video is already downloaded!")
        existing_video: Video = find_existing_video_by_url(metadata["url"])
        if existing_video:
            new_metadata = existing_video.to_json()
            if new_metadata["status"] in [STATUS_COMPLETED, STATUS_DOWNLOADING]:
                new_metadata["duplicate"] = new_metadata["video_id"]
                new_metadata["title"] = metadata["title"]
                new_metadata["source"] = metadata["source"]
                new_metadata["content_warning"] = metadata["content_warning"]
                new_metadata["video_id"] = file_name
                new_metadata["status"] = STATUS_COMPLETED

                write_metadata(file_name, new_metadata)
                log.info(f"Tagged {file_name} as duplicate and linked to original.")

                return True

    if ".m3u8" in metadata["url"]:
        log.warning(f"Skipping .m3u8: {metadata['url']}")
        metadata["status"] = STATUS_INVALID
        write_metadata(file_name, metadata)
        return False

    try:
        d = get_content_info(metadata["url"])
    except AgeRestrictedError:
        log.error("Need cookies for age restricted videos...")
        metadata["status"] = STATUS_COOKIES
        write_metadata(file_name, metadata)
        return False

    video_formats = list(d["video_formats"].keys())
    video_links = d["video_formats"]
    if not len(video_formats):
        log.error("No video stream to download.")
        metadata["status"] = STATUS_INVALID
        write_metadata(file_name, metadata)
        return False

    audio_formats = list(d["audio_formats"].keys())
    audio_links = d["audio_formats"]
    sub_formats = list(d["sub_formats"].keys())
    sub_links = d["sub_formats"]
    duration = d["duration"]
    video_title = d["title"]

    video_url = video_links[video_formats[-1]]["url"]
    if len(audio_formats):
        audio_url = audio_links[audio_formats[-1]]
    else:
        audio_url = ""
    if len(sub_formats):
        sub_url = sub_links[sub_formats[-1]]
    else:
        sub_url = ""

    cmd = get_ffmpeg_cmd(video_url, audio_url, sub_url, vid_save_path)

    metadata["video_title"] = video_title
    metadata["format"] = video_formats[-1]
    metadata["duration"] = duration
    metadata["status"] = STATUS_DOWNLOADING

    write_metadata(file_name, metadata)

    result = subprocess.run(cmd)

    if result.returncode != 0:
        log.error(result)
        log.error("Well this all went to shit. Removing video.")

        try:
            os.remove(vid_save_path)
        except FileNotFoundError:
            pass

        metadata["status"] = STATUS_FAILED
        # with open(url_file_path, "r") as f:
        #     lines = f.readlines()
        # with open(url_file_path, "w") as f:
        #     for line in lines:
        #         if line.strip("\n") != metadata["url"]:
        #             f.write(line)
    else:
        metadata["status"] = STATUS_COMPLETED

    with open(url_file_path, "a") as url_file:
        url_file.write(metadata["url"] + "\n")

    write_metadata(file_name, metadata)

    if result.returncode == 0:
        return True
    return False


def get_ffmpeg_cmd(
    vid_url, aud_url, sub_url, save_path, local_audio_channel=-1, normalize=True,
    http_persistent=True
) -> list:

    cmd = ["ffmpeg", "-i"]

    if len(vid_url):
        cmd.append(vid_url)
        if len(aud_url):
            cmd += ["-i", aud_url]
        if len(sub_url):
            cmd += ["-i", sub_url]
        if len(aud_url):    # Mapping WITH sound
            cmd += ["-map", "0:v", "-map", "1:a"]
            if len(sub_url):    # Mapping WITH sound and WITH subtitles
                cmd += ["-map", "2:s", "-c:s", "mov_text"]
            cmd += ["-c:a", "libopus"]

        elif local_audio_channel >= 0:
            c = local_audio_channel     # Mapping with built in audio
            cmd += ["-map", "0:v", "-map", "0:a:" + str(c), "-c:a:" + str(c), "copy", "-strict",  "-2", "-c:a:" + str(c), "aac", "-ac", "2"]
        elif len(sub_url):  # No sound, only subitles
            cmd += ["-map", "1:s", "-c:s", "mov_text"]

        cmd += ["-vf", "yadif=parity=auto"]
        cmd += ["-c:v", "libx264", "-f", "mp4"]
    
    # Only audio, export to ogg.
    elif len(aud_url):
        cmd += [aud_url]
        cmd += ["-c:a", "libopus", "-f", "ogg"]

    # Apply sound normalization
    if normalize:
        # dynamic norm
        cmd += ["-af", "dynaudnorm=p=0.85"]

        # linear norm
        # cmd += ["-af", "loudnorm=I=-16:TP=-1.5:LRA=11"]

    if http_persistent:
        cmd += ["-http_persistent", "1"]
    else:
        cmd += ["-http_persistent", "0"]

    cmd += ["-y", save_path]

    return cmd


def find_existing_video_by_url(url: str):
    from app.serve.db import Video
    try:
        return Video.query.filter_by(url=url).first()
    except Exception as e:
        log.error(e)
        log.error(f"Unable to get video from database.")
        return None


def find_existing_video_id_by_url(url: str) -> str:
    for f in os.listdir(media_path):
        if f.endswith(".json"):
            try:
                with open(os.path.join(media_path, f)) as jf:
                    d = json.load(jf)
                    if d["url"] == url:
                        if "duplicate" in d.keys():
                            if len(d["duplicate"]):
                                continue
                        return f.split(".json")[0]
            except json.JSONDecodeError:
                continue
    return ""


def generate_thumbnail(
        video_path: str,
        save_path: str,
        width=640,
        height=264,
        blur=False
) -> bool:
    import cv2



def get_celery_scheduled():
    if not inspector:
        return []

    s = []
    try:
        i = inspector.scheduled()
    except:
        i = None

    if i:
        if len(i.keys()):
            k = list(i.keys())[0]
            a = i[k]


def get_celery_active():
    if not inspector:
        return []
    a = []
    try:
        i = inspector.active()
    except:
        i = None

    if i:
        if len(i.keys()):
            k = list(i.keys())[0]
            a = i[k]

    return a



if __name__ == "__main__":
    download_video(
        "https://rr9---sn-uxaxovg-vnaee.googlevideo.com/videoplayback?expire=1645245333&ei=NR8QYr-MENTJyQX_t4OACw&ip=2a02%3A2121%3A348%3A4446%3A10%3A2030%3A4050%3A2&id=o-ALeH5AJ4EFS3jd7JmT4n3wqUJVDGzdzd1VoGQ9a7GG88&itag=134&aitags=133%2C134%2C135%2C136%2C137%2C160%2C242%2C243%2C244%2C247%2C248%2C278%2C394%2C395%2C396%2C397%2C398%2C399&source=youtube&requiressl=yes&mh=D9&mm=31%2C29&mn=sn-uxaxovg-vnaee%2Csn-5go7ynld&ms=au%2Crdu&mv=m&mvi=9&pl=45&initcwndbps=1733750&vprv=1&mime=video%2Fmp4&ns=j-jWRtzzhaM_EIbeSt022XEG&gir=yes&clen=10563747&dur=671.237&lmt=1645152417253074&mt=1645223348&fvip=3&keepalive=yes&fexp=24001373%2C24007246&c=WEB&txp=5535434&n=NitbMne41cfvwE91N&sparams=expire%2Cei%2Cip%2Cid%2Caitags%2Csource%2Crequiressl%2Cvprv%2Cmime%2Cns%2Cgir%2Cclen%2Cdur%2Clmt&sig=AOq0QJ8wRQIhAO4EQxTPvCXqWuRzQBWtWGy7yWJ7EeoNdrnJgd08ZvP7AiB363rWmaI8Q0PEz9PZ1GMXNN_okwgufV-t-P_rnKx-yA%3D%3D&lsparams=mh%2Cmm%2Cmn%2Cms%2Cmv%2Cmvi%2Cpl%2Cinitcwndbps&lsig=AG3C_xAwRQIhAMCjcsawNwRFPFRFr6cFnPp_SI7q526biJlrD9nn5SgBAiBYkGGtUTDFDwB75aWNxekWphIUXbf4wQpmzQi6QJAaPg%3D%3D",
        "https://rr9---sn-uxaxovg-vnaee.googlevideo.com/videoplayback?expire=1645245382&ei=Zh8QYuTaGsnvyQW1oKzwCw&ip=2a02%3A2121%3A348%3A4446%3A10%3A2030%3A4050%3A2&id=o-AH-GmHLDmdxfUifh6MiZQ0BAAisYVpYCYUhx_gQpCg5r&itag=250&source=youtube&requiressl=yes&mh=D9&mm=31%2C29&mn=sn-uxaxovg-vnaee%2Csn-5go7ynld&ms=au%2Crdu&mv=m&mvi=9&pcm2cms=yes&pl=45&initcwndbps=1803750&vprv=1&mime=audio%2Fwebm&ns=5Utx-DOvqnMih9M12BtNJYMG&gir=yes&clen=6065299&dur=671.261&lmt=1645149148063252&mt=1645223578&fvip=3&keepalive=yes&fexp=24001373%2C24007246&c=WEB&txp=5532434&n=YuW1MUOjMKnvXIHZC&sparams=expire%2Cei%2Cip%2Cid%2Citag%2Csource%2Crequiressl%2Cvprv%2Cmime%2Cns%2Cgir%2Cclen%2Cdur%2Clmt&sig=AOq0QJ8wRQIhAKQksmG6Fo5SkUSI-XnxKHGexRKC7MnSJ3P3qKlrnuUXAiAHKJdD0u5yi4CRGGICYyJ7Ap-EoLyXormsDZTCO_3VrA%3D%3D&lsparams=mh%2Cmm%2Cmn%2Cms%2Cmv%2Cmvi%2Cpcm2cms%2Cpl%2Cinitcwndbps&lsig=AG3C_xAwRAIgW07Ly1M8T5mIQ1EadfTzHkbpDWs6unS_mWr5oAhjj2sCIHjLLHF9vl0sy4S66AqEHcadIk8Gd_mITtSpctQxqRkR",
        "test.mp4", start=340, end=360
    )
