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
from dateutil import parser
from dateutil.parser._parser import ParserError
from urllib.parse import urlparse
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError
from dotenv import load_dotenv

from . import json_path, tmp_path, original_path,\
    STATUS_DOWNLOADING, STATUS_INVALID
from .helpers import reverse_readline, get_og_tags, find_between, remove_links, fix_reddit_old, fix_youtube_shorts, \
    program_path, remove_emoji

API_SITES = {
    "twitter.com": "twitter", "www.twitter.com": "twitter", "t.co": "twitter", "www.t.co": "twitter",
    "reddit.com": "reddit", "www.reddit.com": "reddit", "old.reddit.com": "reddit"
}
AD_DESCRIPTIONS = [
    "subscribe", "premium", "% off", "discount", "sign up for", "patreon", "kickstarter",
    "this channel", "check out my", "my channel", "promotion", "click here:", "on instagram", "on twitter",
    "on facebook", "ad-free", "watch more", "around the clock coverage", "trusted news",
    "in-depth channel:", "auto-generated", "breaking news videos", "read the sun", "____", "to read this story",
    "facebook:", "twitter:", "instagram:", "tumblr:", "news for more", "news here:", "more videos from",
    "with the latest news", "my instagram", "my facebook", "my twitter", "my youtube", "contact me",
    "thank you for your", "paypal", "with latest headlines", "sports and entertainment", "also watch",
    "most watched", "contacts:", "----", "read more :", "read more:", "watch our live", "available on youtube",
    "nocomment:", "follow us on", "for more content", "download our", "available in ", "find more information here",
    "watch the latest", "website:", "connect with today", "for the latest developments in", "apple:", "android ",
    "original article:", "original video:", "homepage:", "ig:", "snap:", "pinterest:", "get the free",
    "join us from any", "more videos:", "travel vlogs", "find us online", "is your source for", "get the latest news",
    "watch us on ", "get our app:", "apple tv:", "android:", "roku:", "fire tv:", "our shows", "podcasts:",
    "feedly:", "flipboard:", "youtube:", "iphone:", "razor:", "for more:", "on social:", "brings you the latest",
    "biggest stories of", "listen now -", "telegram:", "website :", "for more news ", "social media:",
    "discord:", "independent journalism", "made possible by supporters", "by patreon", "latest updates", "snapchat:",
    "street journal:", "google+:", ".com:", "more video:", "video center:", "and check out the", "all rights reserved",
    "©", "youtube.com/", "share this video", "accept bitcoin", "our merchandise", "merch store", "demonetize",
    "we need your support", "channel page:", "follow me..", "more videos here:", "(merch)", "available here:",
    "watch and listen to", "read the latest ", "top stories:", "24/7 here:", "24/7:", "support the channel",
    "thanks to our co-producers", "get breaking news", "our patron", "want early access", "videos without ads",
    "follow the story here", "connect with us on", "social media handles:", "news on the hour",
    "business inquiries:", "please help the channel", "youtube algorithm", "subscribe:", "wallet:", "@gmail.com",
    "btc:", "xtz:", "tron:", "eth:", "brought to you by", "other crypto options", "your daily video", "we track news",
    "reporting free for millions by"
]
IGNORED = ["usa", "invasion", "ukrainewar", "ukrainerussia", "russianinvasion", "europe", "warinukraine"]
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


def load_metadata_from_disk(json_path: str) -> dict:
    try:
        if os.path.isfile(json_path):
            with open(json_path, "r") as f:
                return json.load(f)
    except OSError as e:
        print(e)

    return {}


def check_duplicate_for_video(video_id: str) -> int:
    from app.serve.db import session_scope, Video
    from app.serve.views import get_possible_duplicates

    with session_scope() as tmp_session:
        video = tmp_session.query(Video).filter_by(video_id=video_id).first()
        if not video:
            return 0

        duplicate_ids = get_possible_duplicates(video_id, tmp_session)
        duplicates = []
        for d_id in duplicate_ids:
            v = tmp_session.query(Video).filter_by(video_id=d_id).first()
            if v:
                duplicates.append(v)

        if len(duplicates):
            for vd in video.duplicates:
                if vd not in duplicates:
                    video.duplicates.remove(vd)
                    if video in vd.duplicates:
                        vd.duplicates.remove(video)
            for d in duplicates:
                if d not in video.duplicates:
                    video.duplicates.append(d)
                    d.duplicates.append(video)
                    tmp_session.add(d)

            tmp_session.add(video)
            tmp_session.commit()
            return len(duplicates)
    return 0


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


def find_duplicate_video_by_url(url: str, include_deleted: bool = False):
    from app.serve.db import Video, DeletedVideo, db_session
    try:
        video = db_session.query(Video).filter(Video.url.contains(url)).first()
        if video:
            return True

        q = db_session.query(DeletedVideo)
        if not include_deleted:
            q = q.filter_by(duplicate=True)
        video = q.filter(DeletedVideo.url.contains(url)).first()
        if video:
            return True

    except Exception as e:
        log.error(e)
    return False


def get_progress_for_video(video) -> float:
    log_path = os.path.join(tmp_path, f"{video.video_id}_progress.log")
    if not os.path.isfile(log_path) or not video.duration:
        log.error(f"No progress to get for {video.video_id}")
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
        log.error("Can't open log file to read progress!")
        pass

    return 0


def get_frame_count_from_log(log_path, max_search=100) -> float:
    try:
        i = 0
        for l in reverse_readline(log_path):
            if l.startswith("frame="):
                ts = l.split("frame=")[1].strip()
                try:
                    return int(ts)
                except (ValueError, TypeError):
                    return 0

            i += 1
            if i >= max_search:
                return 0
    except OSError:
        log.error("Can't open log file to read frame count!")
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
        elif "mp4" in url and "fmp4" not in url:
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
        if "1920x1080" in f and limit >= 1080:
            return f, False
    for f in reversed(formats):
        if "1080p" in f and limit >= 1080:
            return f, False
    for f in reversed(formats):
        if "720p" in f and limit >= 720:
            return f, False
    for f in reversed(formats):
        if "http" not in f:
            return f, False
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
        "theatres": "",
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
        metadata["theatres"] = data["theatre"]
    except KeyError:
        pass

    try:
        if isinstance(data["content_warning"], str):
            metadata["content_warning"] = data["content_warning"] if data["content_warning"] != "default" else ""
        elif isinstance(data["content_warning"], list):
            metadata["tags"] = data["content_warning"]
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
        if isinstance(data["category"], str):
            metadata["category"] = data["category"] if data["category"] != "default" else ""
        elif isinstance(data["content_warning"], list):
            metadata["categories"] = data["category"]
    except KeyError:
        pass
    try:
        if data["private-checkbox"] == "on":
            metadata["private"] = True
    except KeyError:
        pass

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


def get_metadata_from_api(url: str) -> str:
    from dotenv import load_dotenv
    load_dotenv()

    metadata = {
        "title": "",
        "desc": "",
        "upload_time": datetime.now()
    }

    u = urlparse(url)
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
                return metadata

            headers["Authorization"] = f"Bearer {token}"
            req_url = f"https://api.twitter.com/2/tweets/{tweet_id}?tweet.fields=text,created_at"
            try:
                r = requests.get(req_url, headers=headers)
            except Exception as e:
                print(e)
                print("Error during API request, returning blank")
                return metadata

            data = r.json()
            try:
                tweet = data["data"]["text"]
            except KeyError as e:
                tweet = ""
            try:
                d = data["data"]["created_at"]
                metadata["upload_time"] = parser.parse(d).replace(tzinfo=None)
            except (KeyError, ParserError) as e:
                metadata["upload_time"] = datetime.now()

            metadata["desc"] = remove_links(tweet).lstrip().rstrip().strip("\t")[:1024]
            metadata["title"] = remove_emoji(remove_links(tweet.split("\n")[0]))[:256].lstrip().rstrip().strip("\t")

        elif API_SITES[u.netloc] == "reddit":
            try:
                page = reddit.submission(url=url)
                if page:
                    d = page.created_utc
                    metadata["upload_time"] = datetime.utcfromtimestamp(d)
                    metadata["desc"] = remove_links(page.selftext)
                    metadata["title"] = remove_emoji(page.title)
            except Exception as e:
                log.error(e)

    return metadata


def get_title_from_api(url: str):
    metadata = get_metadata_from_api(url)
    return metadata["title"]


def get_description_from_api(url: str) -> str:
    metadata = get_metadata_from_api(url)
    return metadata["desc"]


def get_upload_time_from_api(url: str) -> str:
    metadata = get_metadata_from_api(url)
    return metadata["upload_time"]


def scrape_metadata_from_source(url: str) -> dict:
    metadata = {}
    url = fix_youtube_shorts(url)
    url = fix_reddit_old(url)

    log.info("Fetching data from YouTube link...")
    ydl = YoutubeDL({
        "cookiefile": program_path("cookies.txt"),
        "noplaylist": True
    })

    video = None

    with ydl:
        try:
            result = ydl.extract_info(
                url,
                download=False
            )
        except DownloadError as e:
            log.error("Error during fetching of video info, doing manual")
            video = None
        except Exception as e:
            log.error(e)
            log.error("Unhandled error during YoutubeDL extraction.")
        else:
            if "entries" in result:
                try:
                    video = result["entries"][0]
                except (IndexError, ValueError, AttributeError):
                    video = None
            else:
                video = result

    if not video:
        log.error("Was not able to find a video on the url given.")
        return metadata

    else:
        if "description" in video:
            desc = video["description"]

        elif "title" in video:
            desc = video["title"]


def get_description_from_source(url: str) -> str:
    desc = ""
    url = fix_youtube_shorts(url)
    url = fix_reddit_old(url)

    log.info("Fetching data from YouTube link...")
    ydl = YoutubeDL({
        "cookiefile": program_path("cookies.txt"),
        "noplaylist": True
    })

    video = None

    with ydl:
        try:
            result = ydl.extract_info(
                url,
                download=False
            )
        except DownloadError as e:
            log.error("Error during fetching of video info, doing manual")
            video = None
        except Exception as e:
            log.error(e)
            log.error("Unhandled error during YoutubeDL extraction.")
        else:
            if "entries" in result:
                try:
                    video = result["entries"][0]
                except (IndexError, ValueError, AttributeError):
                    video = None
            else:
                video = result

    if not video:
        log.error("Was not able to find a video on the url given.")
        return desc
    else:
        if "description" in video:
            desc = video["description"]

        elif "title" in video:
            desc = video["title"]

    return clean_description(desc)


def clean_description(desc: str):
    desc = remove_links(desc)
    desc_segs = desc.split("\n")
    ok = []
    for ds in desc_segs:
        if any(x in ds.lower() for x in AD_DESCRIPTIONS):
            continue
        elif ds.count("#") > 4:
            continue
        ok.append(ds)

    desc = "\n".join(ok)
    desc = strip_useless(desc)
    return desc[:1024]


def strip_useless(s: str):
    s = s.replace("#News", "").replace("#NEWS", "").replace("#news", "")
    s = s.replace("#GetCloserToTheNews", "")
    out = re.findall(r"[0-9]{1,2}:[0-9]{2}", s)
    out_2 = re.findall(r"#(\w+)", s)
    for o in out:
        s = s.replace(o, "")
    for o in out_2:
        if o.lower() in IGNORED:
            s = s.replace(o, "")
    s = s.replace("\n", " ")
    s = s.replace("\t", " ")
    s = s.replace("@", "")
    s = s.replace("#", "")
    s = s.replace("&amp;", "&")
    s = s.replace("Facebook", "").replace("Twitter", "").replace("Instagram", "")
    s = s.replace("     ", " ")
    s = s.replace("    ", " ")
    s = s.replace("   ", " ")
    s = s.replace("  ", " ")
    s = s.replace("\t", " ")
    s = s.replace("  ", " ")
    s = s.replace(" ,", ",")
    s = s.replace(" ,", ",")
    if s.startswith(":") or s.startswith(".") or s.startswith(";") or s.startswith("_"):
        s = s[1:]
    return s.lstrip().rstrip()


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
