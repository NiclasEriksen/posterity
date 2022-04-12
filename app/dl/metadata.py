import os
import logging
import json
import ffmpeg
import re
import requests
import codecs
import praw
from prawcore.exceptions import NotFound
from datetime import datetime
from urllib.parse import urlparse
from dotenv import load_dotenv
from . import json_path, tmp_path, original_path,\
    STATUS_DOWNLOADING, STATUS_INVALID
from .helpers import reverse_readline, get_og_tags, find_between, remove_links

API_SITES = {
    "twitter.com": "twitter", "www.twitter.com": "twitter", "t.co": "twitter", "www.t.co": "twitter",
    "reddit.com": "reddit", "www.reddit.com": "reddit", "old.reddit.com": "reddit"
}
reddit = praw.Reddit(
    client_id=os.environ.get("REDDIT_CLIENT_ID", ""),
    client_secret=os.environ.get("REDDIT_CLIENT_SECRET", ""),
    user_agent="Posterity title fetcher",
    username=os.environ.get("REDDIT_USER", ""),
    password=os.environ.get("REDDIT_PW", "")
)

load_dotenv()
log = logging.getLogger("posterity_dl.metadata")


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
    json_save_path = os.path.join(json_path, video_id + ".json")
    try:
        with open(json_save_path, "w") as json_file:
            json.dump(md, json_file)
    except OSError as e:
        log.error(e)
        log.error(f"JSON for {video_id} was not written to disk.")


def write_metadata(video_id: str, md: dict):
    write_metadata_to_disk(video_id, md)
    write_metadata_to_db(video_id, md)


def add_technical_info_to_all():
    from app.serve.db import session_scope, Video
    with session_scope() as db_session:
        videos = db_session.query(Video).all()
        for v in videos:
            p = os.path.join(original_path, v.video_id + ".mp4")
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


def get_progress_for_video(video) -> float:
    log_path = os.path.join(tmp_path, f"{video.video_id}_progress.log")
    if not os.path.isfile(log_path) or not video.duration:
        return 0.0
    progress_time = get_last_time_from_log(log_path)
    if progress_time <= 0:
        return 0.0
    elif progress_time >= video.duration:
        return 1.0

    return progress_time / video.duration


def get_last_time_from_log(log_path, max_search=100) -> float:
    try:
        i = 0
        for l in reverse_readline(log_path):
            if l.startswith("out_time="):
                ts = l.split("out_time=")[1].strip()
                try:
                    hrs, mins, sec = ts.split(":")
                except ValueError:  # not enough/too many
                    hrs, mins, sec = "00", "00", "00.00"
                try:
                    hrs, mins, sec = int(hrs), int(mins), float(sec)
                except (TypeError, ValueError):
                    hrs, mins, sec = 0, 0, 0.0

                time = (hrs * 3600) + (mins * 60) + sec
                return time

            i += 1
            if i >= max_search:
                return 0
    except OSError:
        pass

    return 0


def get_source_site(url: str) -> str:
    u = urlparse(url)
    if len(u.netloc):
        if any(
            r in u.netloc for r in ["reddit.com", "redd.it", "redditinc.com", "redditmedia.com", "redditstatic.com"]
        ):
            return "reddit"
        if any(r in u.netloc for r in ["twitter.co", "t.co", "periscope.tv", "pscp.tv", "twimg.com", "twttr.com"]):
            return "twitter"
        if any(r in u.netloc for r in ["youtube.", "ytimg.com", "youtu.be", "googlevideo.com"]):
            return "youtube"
        if any(
            r in u.netloc for r in [
                "twitch.com", "live-video.net", "twitch.tv", "ttvnw.net", "jtvnw.net", "twitchcdn.net", "twitchsvc.net"
            ]
        ):
            return "twitch"
        if any(r in u.netloc for r in ["facebook.com", "fb.com", "fb.gg", "fbcdn.net", "fbwat.ch", "facebook.net"]):
            return "facebook"
        if any(r in u.netloc for r in ["discord.com", "discord.gg", "discord.media", "discordapp."]):
            return "discord"
        if any(r in u.netloc for r in ["instagram.com", "cdninstagram.com", "ig.me"]):
            return "instagram"
        if any(r in u.netloc for r in ["vimeo.com", "vhx.com", "vhx.tv", "vimeocdn.com"]):
            return "vimeo"
    return ""


def find_highest_quality_url(urls: list) -> str:
    points = {
        "1080p": 6, "1080": 5,
        "720p": 5, "720": 4,
        "540p": 3, "540": 3,
        "360p": 2, "360": 2,
        "280p": 1, "280": 1,
        "270p": 1, "270": 1,
        "hq": 5, "hd": 4,
        "high": 5, "hi": 2,
        "medium": 3, "med": 2
    }
    tally = {}
    for url in urls:
        best = 0
        for tag, score in points.items():
            if tag in url.lower() and score > best:
                best = score

        if ".mp4" in url:
            best += 10
        elif "mp4" in url:
            best += 5
        elif ".mkv" in url:
            best += 3
        elif ".ogv" in url:
            best += 3
        if (
            url.lower().endswith(".m3u8") or
            url.lower().endswith(".f4m") or
            ".m3u8?" in url.lower() or
            ".m3u8&" in url.lower()
        ):
            best = max(0, int(best * 0.25))
        elif ".m3u8" in url.lower():
            best = max(0, int(best * 0.5))
        if "preview" in url.lower():
            best = max(0, int(best * 0.1))

        tally[url] = best

    best_score = max([s for _k, s in tally.items()])

    for url in urls:
        if tally[url] == best_score:
            return url
    # If for some reason none was found lol. Late.
    return urls[0]


def get_title_from_html(html: str) -> list:
    title = "No title"
    titles = get_og_tags(html, title_only=True)
    if len(titles) > 0:
        title = titles[0]
    else:
        titles = re.findall(r"<title>(.*?)</title>", html)
        if len(titles) > 0:
            title = titles[0]
        else:
            titles = get_og_tags(html, title_only=False)    # Broader search
            if len(titles) > 0:
                title = titles[0]

    return title.lstrip().rstrip()


def get_source_links(url: str) -> (str, list):
    headers = {'Accept-Encoding': 'identity'}

    if "://t.me" in url and not "embed=1" in url:
        url += "?embed=1"

    try:
        r = requests.get(url, headers=headers)
    except:
        log.error("Unable to download page?!")
        return "No title (missing)", []

    html = r.text

    title = get_title_from_html(html)
    if title == "No title":
        title += " (mp4)"

    urls = []
    elements = re.findall(r'[\'"]?([^\'" >]+)', html)

    if "://t.me" in url:
        if "grouped_media" in html:
            log.error("Multiple videos, link individual Telegram page!")
            return "Multiple videos on page", []

    if "contentURL" in html and ".mp4" in html:
        l = find_between(html, "contentURL\":\"", "\"")
        if l.count("://") == 1:
            log.info("Found mp4 link in javascript!")
            urls.append(codecs.decode(l, 'unicode-escape'))

    for e in elements:
        if e.lower().endswith(".mp4"):
            urls.append(codecs.decode(e, 'unicode-escape'))
        elif "http" in e.lower() and ".mp4" in e.lower():
            urls.append(codecs.decode(e, 'unicode-escape'))

    return title, urls


def technical_info(video_path: str) -> dict:
    info = {
        "file_size": 0,
        "duration": 0.0,
        "dimensions": (0, 0),
        "bit_rate": 0.0,
        "vid_bit_rate": 0.0,
        "aud_bit_rate": 0.0,
        "fps": 0.0,
        "audio": False,
        "audio_codec": "",
        "video_codec": "",
    }
    if not os.path.isfile(video_path):
        return info

    try:
        probe = ffmpeg.probe(video_path)
    except ffmpeg.Error as e:
        print(e)
        info["file_size"] = os.path.getsize(video_path)
        return info

    if "format" in probe.keys():
        if "bit_rate" in probe["format"]:
            try:
                info["bit_rate"] = int(probe["format"]["bit_rate"])
            except (ValueError, TypeError):
                pass
        if "duration" in probe["format"]:
            try:
                info["duration"] = float(probe["format"]["duration"])
            except (ValueError, TypeError):
                pass
        if "size" in probe["format"]:
            try:
                info["file_size"] = int(probe["format"]["size"])
            except (ValueError, TypeError):
                pass
        if "size" in probe["format"]:
            try:
                info["file_size"] = int(probe["format"]["size"])
            except (ValueError, TypeError):
                pass

    if "streams" in probe.keys():
        for stream in probe["streams"]:
            if "codec_type" not in stream:
                print("Skipping stream...")
                print(stream)
                continue

            if stream["codec_type"] == "video":
                if "codec_name" in stream:
                    info["video_codec"] = stream["codec_name"]
                elif "codec_tag_string" in stream:
                    info["video_codec"] = stream["codec_tag_string"]
                elif "codec_long_name" in stream:
                    info["video_codec"] = stream["codec_long_name"]
                if "width" in stream and "height" in stream:
                    try:
                        info["dimensions"] = (
                            int(stream["width"]),
                            int(stream["height"])
                        )
                    except (ValueError, TypeError):
                        pass

                if "avg_frame_rate" in stream:
                    fps = stream["avg_frame_rate"]

                    try:
                        if "/" in fps:
                            total, divisor = fps.split("/")
                            info["fps"] = float(total) / float(divisor)
                        else:
                            info["fps"] = float(fps)
                    except (ValueError, TypeError, AttributeError):
                        pass

                if "bit_rate" in stream:
                    try:
                        info["vid_bit_rate"] = int(stream["bit_rate"])
                    except (ValueError, TypeError):
                        pass

            elif stream["codec_type"] == "audio":
                if "codec_name" in stream:
                    info["audio_codec"] = stream["codec_name"]
                elif "codec_tag_string" in stream:
                    info["audio_codec"] = stream["codec_tag_string"]
                elif "codec_long_name" in stream:
                    info["audio_codec"] = stream["codec_long_name"]
                if "bit_rate" in stream:
                    try:
                        info["aud_bit_rate"] = int(stream["bit_rate"])
                    except (ValueError, TypeError):
                        pass
                info["audio"] = True
            elif stream["codec_type"] == "subtitle":
                pass

    return info


def find_best_format(formats_dict: dict, limit: int=2160) -> (str, bool):
    formats_dict = formats_dict.copy()
    invalid_ids = [f_id for f_id, i in formats_dict.items() if min(i["dimensions"]) > limit]
    for i in invalid_ids:
        formats_dict.pop(i, None)

    best = None
    best_audio = None
    highest_res = 0
    highest_audio = 0
    for f_id, info in formats_dict.items():
        if min(info["dimensions"]) >= highest_audio and info["audio"]:
            highest_audio = min(info["dimensions"])
            best_audio = f_id
        elif min(info["dimensions"]) >= highest_res:
            highest_res = min(info["dimensions"])
            best = f_id

    if best_audio and highest_audio >= highest_res:
        return best_audio, True

    if best and highest_res > 0:
        return best, False

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
    return formats[-1], False


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
        "private": False,
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
    try:
        if data["private-checkbox"] == "on":
            metadata["private"] = True
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
    except KeyError as e:
        log.error(e)

    return metadata


def get_title_from_api(url: str):
    from dotenv import load_dotenv
    load_dotenv()

    headers = {
        'Accept-Encoding': 'identity',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.75 Safari/537.36',
    }

    u = urlparse(url)
    if u.netloc in API_SITES:
        if API_SITES[u.netloc] == "twitter":
            try:
                tweet_id = int(u.path.split("/")[-1])
            except (ValueError, IndexError, TypeError):
                tweet_id = 0

            token = os.environ.get("TWITTER_BEARER_TOKEN", "")
            if not len(token) or not tweet_id:
                return ""

            headers["Authorization"] = f"Bearer {token}"
            req_url = f"https://api.twitter.com/2/tweets/{tweet_id}?tweet.fields=text"
            try:
                r = requests.get(req_url, headers=headers)
            except:
                return ""
                pass

            data = r.json()
            try:
                tweet = data["data"]["text"]
            except KeyError:
                return ""

            return remove_links(tweet.split("\n")[0])[:256].lstrip().rstrip().strip("\t")

        elif API_SITES[u.netloc] == "reddit":
            try:
                page = reddit.submission(url=url)
                if page:
                    return page.title
            except Exception as e:
                log.error(e)
            return ""

        return ""


def get_description_from_api(url: str) -> str:
    u = urlparse(url)
    desc = ""
    headers = {
        'Accept-Encoding': 'identity',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.75 Safari/537.36',
    }
    if u.netloc in API_SITES:

        if API_SITES[u.netloc] == "twitter":
            try:
                tweet_id = int(u.path.split("/")[-1])
            except (ValueError, IndexError, TypeError):
                tweet_id = 0

            token = os.environ.get("TWITTER_BEARER_TOKEN", "")
            if not len(token) or not tweet_id:
                return ""

            headers["Authorization"] = f"Bearer {token}"
            req_url = f"https://api.twitter.com/2/tweets/{tweet_id}?tweet.fields=text"
            try:
                r = requests.get(req_url, headers=headers)
            except:
                pass

            data = r.json()
            try:
                tweet = data["data"]["text"]
            except KeyError as e:
                tweet = ""

            desc = remove_links(tweet).lstrip().rstrip().strip("\t")[:1024]

        elif API_SITES[u.netloc] == "reddit":
            try:
                page = reddit.submission(url=url)
                if page:
                    desc = page.title
            except Exception as e:
                log.error(e)

    return desc


if __name__ == "__main__":
    # from pprint import pprint
    # pprint(technical_info("/home/fredspipa/Videos/bagdad.mp4"))
    # pprint(technical_info("/home/fredspipa/Videos/awkw.mp4"))
    # pprint(technical_info("/home/fredspipa/Videos/shortlegcat.mp4"))
    # pprint(technical_info("/home/fredspipa/Videos/traktor.mp4"))
    # pprint(technical_info("/home/fredspipa/Videos/Serotonin/Serotonin.mlt"))
    # pprint(technical_info("/home/fredspipa/Videos/whatimret.mp4"))
    # generate_video_images(
    #     "/home/fredspipa/Videos/whatimret.mp4",
    #     "/home/fredspipa/Videos/thumb.png",
    #     "/home/fredspipa/Videos/preview.png",
    #     "/home/fredspipa/Videos/thumb_blurred.png",
    #     "/home/fredspipa/Videos/preview_blurred.png",
    #     start=5,
    #     blur_amount=0.75,
    #     desaturate=True
    # )
    pass
