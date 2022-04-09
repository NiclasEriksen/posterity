import logging
import json
import os
import subprocess
from datetime import datetime
from typing import Union
from .helpers import seconds_to_time, resource_path, unique_filename
from .youtube import valid_video_url, get_content_info, AgeRestrictedError
from .metadata import generate_video_images, technical_info
from app import celery
from werkzeug.local import LocalProxy
from flask import current_app


# log = LocalProxy(lambda: current_app.logger)
log = logging.getLogger("posterity_dl.dl")

if celery:
    inspector = celery.control.inspect()

media_path = os.environ.get("MEDIA_FOLDER", "")
thumbnail_path = os.environ.get("THUMBNAIL_FOLDER", "")
preview_path = os.environ.get("PREVIEW_FOLDER", "")
url_file_path = os.path.join(media_path, "urls.store")
tmp_path = os.path.join(media_path, "tmp")

STATUS_DOWNLOADING = 0
STATUS_COMPLETED = 1
STATUS_FAILED = 2
STATUS_INVALID = 3
STATUS_COOKIES = 4
STATUS_PENDING = 5
STATUS_PROCESSING = 6
CRF = 26
CRF_LOW = 35
MAX_DURATION_HD: float = 30 * 60.0
MAX_RESOLUTION_MD: int = 720
MAX_DURATION_MD: float = 60 * 60.0
MAX_RESOLUTION_SD: int = 480
MAX_DURATION_SD: float = 480 * 60.0     # 8 hours maximum.
MIN_BIT_RATE_PER_PIXEL = 0.5
MAX_BIT_RATE_PER_PIXEL = 2.75
MAX_AUD_BIT_RATE = 128
MAX_FPS = 60
SPLIT_FPS_THRESHOLD = 40.0


if not os.path.isfile(url_file_path):
    open(url_file_path, "a").close()


def write_metadata_to_db(video_id: str, md: dict):
    try:
        from app.serve.db import session_scope, Video
        with session_scope() as db_session:
            existing = db_session.query(Video).filter_by(video_id=video_id).first()

            if existing:
                video = existing
            else:
                video = Video()

            video.from_json(md)

            db_session.add(video)
            db_session.commit()

    except Exception as e:
        log.error(e)
        log.error(f"Unable to write video {video_id} to database.")


def write_metadata_to_disk(video_id: str, md: dict):
    json_save_path = os.path.join(media_path, video_id + ".json")
    try:
        with open(json_save_path, "w") as json_file:
            json.dump(md, json_file)
    except OSError as e:
        log.error(e)
        log.error(f"JSON for {video_id} was not written to disk.")


def write_metadata(video_id: str, md: dict):
    write_metadata_to_disk(video_id, md)
    write_metadata_to_db(video_id, md)


def process_from_json_data(metadata: dict, input_file: str, output_file: str) -> dict:
    metadata["status"] = STATUS_PROCESSING
    yield metadata

    info = technical_info(input_file)

    vid_bit_rate = info["vid_bit_rate"]
    aud_bit_rate = info["vid_bit_rate"]
    fps = info["fps"]

    try:
        pixels = (info["dimensions"][0] * info["dimensions"][1])
    except (KeyError, IndexError):
        pixels = 921600     # 720p

    max_bit_rate = pixels * MAX_BIT_RATE_PER_PIXEL
    min_bit_rate = pixels * MIN_BIT_RATE_PER_PIXEL
    r = max_bit_rate - min_bit_rate
    br = min(1.0, max(0.0, vid_bit_rate - min_bit_rate) / r)

    crf = int(CRF + (CRF_LOW - CRF) * br)

    print(max_bit_rate)
    print(f"CRF: {crf}, BR: {br}")
    vid_bit_rate = min(vid_bit_rate, max_bit_rate) // 1000
    aud_bit_rate = min(aud_bit_rate // 1000, MAX_AUD_BIT_RATE)


    if fps >= SPLIT_FPS_THRESHOLD and fps <= MAX_FPS:
        fps *= 0.5
    elif fps > MAX_FPS:
        fps = MAX_FPS

    # print(vid_bit_rate)
    # print(aud_bit_rate)

    cmd = get_post_process_ffmpeg_cmd(
        input_file, output_file,
        fps=fps, vid_bit_rate=vid_bit_rate,
        aud_bit_rate=aud_bit_rate, crf=crf
    )

    # metadata["processed_bit_rate"] = (vid_bit_rate + aud_bit_rate) * 1000
    # metadata["processed_frame_rate"] = (vid_bit_rate + aud_bit_rate) * 1000

    if "&&" in cmd:
        pass_1 = cmd[:cmd.index("&&")]
        pass_2 = cmd[cmd.index("&&")+1:]
    else:
        pass_1 = cmd
        pass_2 = []

    cur_dir = os.getcwd()
    #os.chdir(tmp_path)

    for i, p in enumerate([pass_1, pass_2]):
        if not len(p):
            continue

        log.info(f"{metadata['video_id']} | Running pass {i}...")
        result = subprocess.run(p)
        if result.returncode != 0:
            log.error(result)
            log.error("Well this all went to shit. Removing video.")
            try:
                os.remove(output_file)
            except (FileNotFoundError, OSError):
                pass
            metadata["status"] = STATUS_FAILED
            break
    else:
        metadata["status"] = STATUS_COMPLETED
        metadata = add_technical_info_to_metadata(metadata, input_file, post_process=False)
        metadata = add_technical_info_to_metadata(metadata, output_file, post_process=True)

    #os.chdir(cur_dir)

    yield metadata


def download_from_json_data(metadata: dict, file_name: str):
    from app.serve.db import Video
    vid_save_path = os.path.join(media_path, file_name + ".mp4")

    if not valid_video_url(metadata["url"]):
        log.error("Invalid video url...")
        metadata["status"] = STATUS_INVALID
        yield metadata

    elif media_path == "":
        log.error("No path to save video (MEDIA_FOLDER)...")
        metadata["status"] = STATUS_FAILED
        yield metadata

    if ".m3u8" in metadata["url"]:
        log.warning(f"Skipping .m3u8: {metadata['url']}")
        metadata["status"] = STATUS_INVALID
        yield metadata

    try:
        d = get_content_info(metadata["url"])
    except AgeRestrictedError:
        log.error("Need cookies for age restricted videos...")
        metadata["status"] = STATUS_COOKIES
        yield metadata

    video_formats = list(d["video_formats"].keys())
    video_links = d["video_formats"]
    if not len(video_formats):
        log.error("No video stream to download.")
        metadata["status"] = STATUS_INVALID
        yield metadata

    audio_formats = list(d["audio_formats"].keys())
    audio_links = d["audio_formats"]
    sub_formats = list(d["sub_formats"].keys())
    sub_links = d["sub_formats"]
    duration = d["duration"]
    video_title = d["title"]

    if duration > MAX_DURATION_SD:
        log.error("Video is too long to download! Duration: " + str(duration))
        metadata["status"] = STATUS_INVALID
        yield metadata

    limit = 2160
    if duration > MAX_DURATION_MD:
        limit = MAX_RESOLUTION_SD
    elif duration > MAX_DURATION_HD:
        limit = MAX_RESOLUTION_MD

    f = find_best_format(d["video_formats"], limit=limit)

    print("================")
    print(f)
    print("================")

    video_url = video_links[f]["url"]

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
    metadata["format"] = f
    metadata["duration"] = duration
    metadata["status"] = STATUS_DOWNLOADING

    yield metadata
    result = subprocess.run(cmd)

    if result.returncode != 0:
        log.error(result)
        log.error("Well this all went to shit. Removing video.")

        try:
            os.remove(vid_save_path)
        except (FileNotFoundError, OSError):
            pass

        metadata["status"] = STATUS_FAILED
        yield metadata

    else:
        metadata["status"] = STATUS_COMPLETED
        try:
            if len(thumbnail_path) and len(preview_path):
                generate_video_images(
                    vid_save_path,
                    os.path.join(thumbnail_path, file_name + "_thumb.jpg"),
                    os.path.join(preview_path, file_name + "_preview.jpg"),
                    os.path.join(thumbnail_path, file_name + "_thumb_blurred.jpg"),
                    os.path.join(preview_path, file_name + "_preview_blurred.jpg"),
                    start=5 if duration >= 10.0 else 0,
                    blur_amount=0.75,
                    desaturate=False,
                    content_text=metadata["content_warning"] if metadata["content_warning"].lower().strip() != "none" else ""
                )
        except Exception as e:
            log.error(e)
            log.error("FAILED THUMBNAIL GENERATION")

        metadata = add_technical_info_to_metadata(metadata, vid_save_path)

    yield metadata


def get_post_process_ffmpeg_cmd(
        input_path: str, output_path: str, queue_size=512,
        fps=25, vid_bit_rate=2000, aud_bit_rate=128, crf=CRF
    ) -> list:

    tmp_file_name = os.path.split(input_path)[1].split(".mp4")[0]

    pass_1 = [
        "ffmpeg", "-thread_queue_size", f"{queue_size}", "-y",
        "-vsync", "vfr",
        "-i", input_path,
        "-c:v", "libx264", "-filter:v", f"yadif=parity=auto[v];[v]fps={fps}", "-pix_fmt", "yuv420p", "-vprofile", "main", "-vlevel", "4", "-preset", "veryslow",
        "-b:v", f"{vid_bit_rate}k", "-crf", str(crf),
        "-c:a", "aac", "-strict", "experimental", "-b:a", f"{aud_bit_rate}k",
        "-passlogfile", tmp_file_name, "-v", "27", output_path
    ]

    return pass_1


    # pass_base = [
    #     "ffmpeg", "-thread_queue_size", f"{queue_size}", "-y",
    #     "-vsync", "vfr",
    #     "-i", input_path,
    #     "-vf", "yadif=parity=auto",
    #     "-c:v", "libx264", "-pix_fmt", "yuv420p", "-vprofile", "main", "-vlevel", "4", "-preset", "veryslow",
    #     "-b:v", f"{vid_bit_rate}k", "-filter:v", f"fps={fps}", "-crf", str(CRF_LOW),
    #     "-c:a", "aac", "-strict", "experimental", "-b:a", f"{aud_bit_rate}k",
    #     "-passlogfile", tmp_file_name, "-pass" #-v 24
    # ]
    #
    # pass_1 = pass_base + ["1", "-f", "mp4", "/dev/null"]
    # pass_2 = pass_base + ["2", output_path]
    # return pass_1 + ["&&"] + pass_2


def get_ffmpeg_cmd(
    vid_url, aud_url, sub_url, save_path, local_audio_channel=-1, normalize=True,
    http_persistent=True, queue_size=512, crf=26
) -> list:

    cmd = ["ffmpeg", "-i", "-thread_queue_size", f"{queue_size}"]

    if len(vid_url):
        cmd.append(vid_url)
        if len(aud_url):
            cmd += ["-i", aud_url]
        # if len(sub_url):
        #     cmd += ["-i", sub_url]
        if len(aud_url):    # Mapping WITH sound
            cmd += ["-map", "0:v", "-map", "1:a"]
            # if len(sub_url):    # Mapping WITH sound and WITH subtitles
            #     cmd += ["-map", "2:s", "-c:s", "mov_text"]
            cmd += ["-c:a", "aac"]

        elif local_audio_channel >= 0:
            c = local_audio_channel     # Mapping with built in audio
            cmd += ["-map", "0:v", "-map", "0:a:" + str(c), "-c:a:" + str(c), "copy", "-strict",  "-2", "-c:a:" + str(c), "aac", "-ac", "2"]
        # elif len(sub_url):  # No sound, only subitles
        #     cmd += ["-map", "1:s", "-c:s", "mov_text"]

        cmd += ["-vf", "yadif=parity=auto"]
        cmd += ["-vcodec", "libx264", "-crf", crf, "-vb", "2500k", "-f", "mp4"]
        # cmd += ["-c:v", "h264", "-f", "mp4"]

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

    cmd += ["-v", "24", "-y", save_path]

    return cmd


def find_existing_video_by_url(url: str):
    from app.serve.db import Video
    try:
        return Video.query.filter_by(url=url).first()
    except Exception as e:
        log.error(e)
        log.error(f"Unable to get video from database.")
        return None


def find_duplicate_video_by_url(url: str):
    from app.serve.db import Video, db_session

    try:
        video = db_session.query(Video).filter(Video.url.contains(url)).first()
        if video:
            return video

    except Exception as e:
        log.error(e)
    return None


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


def find_best_format(formats_dict: dict, limit: int=2160):
    formats_dict = formats_dict.copy()
    invalid_ids = [f_id for f_id, i in formats_dict.items() if min(i["dimensions"]) > limit]
    for i in invalid_ids:
        formats_dict.pop(i, None)

    best = None
    highest_res = 0
    for f_id, info in formats_dict.items():
        if min(info["dimensions"]) >= highest_res:
            highest_res = min(info["dimensions"])
            best = f_id

    if best and highest_res > 0:
        return best

    # If lacking dimensions and stuff
    formats = list(formats_dict.keys())
    for f in reversed(formats):
        if "1920x1080" in f:
            return f
    for f in reversed(formats):
        if "1080p" in f:
            return f
    for f in reversed(formats):
        if "720p" in f:
            return f
    print(formats[-1])
    return formats[-1]


def parse_input_data(data: dict) -> dict:
    metadata = {
        "url": "",
        "source": "Unknown",
        "title": "",
        "video_title": "",
        "content_warning": "",
        "category": "",
        "file_size": 0,
        "bit_rate": 0,
        "frame_rate": 0.0,
        "width": 0,
        "height": 0,
        "format": "",
        "duration": 0,
        "upload_time": datetime.now().timestamp(),
        "status": STATUS_DOWNLOADING,
        "video_id": "",
        "verified": False,
    }
    try:
        metadata["url"] = data["url"]
        metadata["title"] = data["title"]
    except KeyError:
        log.error("Corrupted data?!")
        metadata["status"] = STATUS_INVALID
        return metadata

    try:
        metadata["content_warning"] = data["content_warning"]
    except KeyError:
        pass

    if "source_user" in data and len(data["source_user"]):
        metadata["source"] = data["source_user"]
    else:
        try:
            metadata["source"] = data["source"]
        except KeyError:
            pass
    try:
        metadata["category"] = data["category"]
    except KeyError:
        pass
    metadata["content_warning"] = metadata["content_warning"].replace("default", "")
    metadata["category"] = metadata["category"].replace("default", "")

    return metadata


def add_technical_info_to_metadata(metadata: dict, video_path: str, post_process=False) -> dict:
    info = technical_info(video_path)
    try:
        if post_process:
            metadata["processed_file_size"] = info["file_size"]
            metadata["processed_bit_rate"] = info["bit_rate"]
            metadata["processed_frame_rate"] = info["fps"]
            metadata["processed_format"] = f'{info["video_codec"]} / {info["audio_codec"]}'
        else:
            metadata["file_size"] = info["file_size"]
            metadata["bit_rate"] = info["bit_rate"]
            metadata["frame_rate"] = info["fps"]
            metadata["duration"] = info["duration"]
            metadata["width"] = info["dimensions"][0]
            metadata["height"] = info["dimensions"][1]
            metadata["format"] = f'{info["video_codec"]} / {info["audio_codec"]}'
    except KeyError:
        log.error(e)

    return metadata


def add_technical_info_to_all():
    from app.serve.db import session_scope, Video
    with session_scope() as db_session:
        videos = db_session.query(Video).all()
        for v in videos:
            p = os.path.join(media_path, v.video_id + ".mp4")
            if os.path.exists(p):
                metadata = v.to_json()
                metadata = add_technical_info_to_metadata(metadata, p)
                v.from_json(metadata)
                db_session.add(v)
                db_session.commit()


def refresh_json_on_all():
    from app.serve.db import session_scope, Video
    with session_scope() as db_session:
        videos = db_session.query(Video).all()
        for v in videos:
            write_metadata_to_disk(v.video_id, v.to_json())


if __name__ == "__main__":
    # download_video(
    #     "https://rr9---sn-uxaxovg-vnaee.googlevideo.com/videoplayback?expire=1645245333&ei=NR8QYr-MENTJyQX_t4OACw&ip=2a02%3A2121%3A348%3A4446%3A10%3A2030%3A4050%3A2&id=o-ALeH5AJ4EFS3jd7JmT4n3wqUJVDGzdzd1VoGQ9a7GG88&itag=134&aitags=133%2C134%2C135%2C136%2C137%2C160%2C242%2C243%2C244%2C247%2C248%2C278%2C394%2C395%2C396%2C397%2C398%2C399&source=youtube&requiressl=yes&mh=D9&mm=31%2C29&mn=sn-uxaxovg-vnaee%2Csn-5go7ynld&ms=au%2Crdu&mv=m&mvi=9&pl=45&initcwndbps=1733750&vprv=1&mime=video%2Fmp4&ns=j-jWRtzzhaM_EIbeSt022XEG&gir=yes&clen=10563747&dur=671.237&lmt=1645152417253074&mt=1645223348&fvip=3&keepalive=yes&fexp=24001373%2C24007246&c=WEB&txp=5535434&n=NitbMne41cfvwE91N&sparams=expire%2Cei%2Cip%2Cid%2Caitags%2Csource%2Crequiressl%2Cvprv%2Cmime%2Cns%2Cgir%2Cclen%2Cdur%2Clmt&sig=AOq0QJ8wRQIhAO4EQxTPvCXqWuRzQBWtWGy7yWJ7EeoNdrnJgd08ZvP7AiB363rWmaI8Q0PEz9PZ1GMXNN_okwgufV-t-P_rnKx-yA%3D%3D&lsparams=mh%2Cmm%2Cmn%2Cms%2Cmv%2Cmvi%2Cpl%2Cinitcwndbps&lsig=AG3C_xAwRQIhAMCjcsawNwRFPFRFr6cFnPp_SI7q526biJlrD9nn5SgBAiBYkGGtUTDFDwB75aWNxekWphIUXbf4wQpmzQi6QJAaPg%3D%3D",
    #     "https://rr9---sn-uxaxovg-vnaee.googlevideo.com/videoplayback?expire=1645245382&ei=Zh8QYuTaGsnvyQW1oKzwCw&ip=2a02%3A2121%3A348%3A4446%3A10%3A2030%3A4050%3A2&id=o-AH-GmHLDmdxfUifh6MiZQ0BAAisYVpYCYUhx_gQpCg5r&itag=250&source=youtube&requiressl=yes&mh=D9&mm=31%2C29&mn=sn-uxaxovg-vnaee%2Csn-5go7ynld&ms=au%2Crdu&mv=m&mvi=9&pcm2cms=yes&pl=45&initcwndbps=1803750&vprv=1&mime=audio%2Fwebm&ns=5Utx-DOvqnMih9M12BtNJYMG&gir=yes&clen=6065299&dur=671.261&lmt=1645149148063252&mt=1645223578&fvip=3&keepalive=yes&fexp=24001373%2C24007246&c=WEB&txp=5532434&n=YuW1MUOjMKnvXIHZC&sparams=expire%2Cei%2Cip%2Cid%2Citag%2Csource%2Crequiressl%2Cvprv%2Cmime%2Cns%2Cgir%2Cclen%2Cdur%2Clmt&sig=AOq0QJ8wRQIhAKQksmG6Fo5SkUSI-XnxKHGexRKC7MnSJ3P3qKlrnuUXAiAHKJdD0u5yi4CRGGICYyJ7Ap-EoLyXormsDZTCO_3VrA%3D%3D&lsparams=mh%2Cmm%2Cmn%2Cms%2Cmv%2Cmvi%2Cpcm2cms%2Cpl%2Cinitcwndbps&lsig=AG3C_xAwRAIgW07Ly1M8T5mIQ1EadfTzHkbpDWs6unS_mWr5oAhjj2sCIHjLLHF9vl0sy4S66AqEHcadIk8Gd_mITtSpctQxqRkR",
    #     "test.mp4", start=340, end=360
    # )
    pass
