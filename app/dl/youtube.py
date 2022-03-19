import youtube_dl
import youtube_dl.utils
import logging
import validators
import re
import requests
from .helpers import program_path, find_between
import codecs


#https://accounts.google.com/signin/v2/identifier?service=youtube
#CLIENTID: 1011910616755-rbvlv952parvd549q0olik45c9somivd.apps.googleusercontent.com
#SECRET  : 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

log = logging.getLogger("klippekort.youtube")


YT_FORMATS = {
    "YT 1080p": "137",
    "YT 720p": "136",
    "YT 720p2": "95",
    "YT 640p": "93",
    "YT 480p": "135",
    "YT 360p": "134",
    "YT 240p": "133",
    "1080p": "1080",
    "720p": "720",
    "480p": "480",
    "360p": "360",
    "240p": "240",
    "MP4 720p": "2409",
    "MP4 576p": "1425",
    "MP4 360p": "626",
    "MP4 240p": "379",
    "MP4 720p 4:3": "2394",
    "MP4 640p 4:3": "1418",
    "MP4 360p 4:3": "639",
    "MP4 240p 4:3": "393",
    "MP4 180p 4:3": "217",
    "MP4 Mobile": "mp4-mobile",
    "Opus VBR 50kbps": "249",
    "Opus VBR 70kbps": "250",
    "Opus VBR 160kbps": "251",
    "AAC 48kbps": "139",
    "AAC 128kbps": "140",
    "HLS audio 0": "hls-0-audio_0",
    "HLS audio 1": "hls-1-audio_0",
}
YT_SIZES = {
    "YT 1080p": (1920, 1080),
    "YT 720p": (1280, 720),
    "YT 720p2": (1280, 720),
    "YT 640p": (640, 360),
    "YT 480p": (854, 480),
    "YT 360p": (640, 360),
    "YT 240p": (426, 240)
}

VID_FORMATS = ["240p", "360p", "480p", "720p", "1080p",
    "YT 1080p", "YT 720p", "YT 720p2", "YT 640p", "YT 480p", "YT 360p", "YT 240p",
    "MP4 720p", "MP4 360p", "MP4 240p", "MP4 576p",
    "MP4 720p 4:3", "MP4 640p 4:3", "MP4 360p 4:3", "MP4 240p 4:3", "MP4 180p 4:3", "MP4 Mobile"
]
AUD_FORMATS = ["HLS audio 0", "HLS audio 1", "Opus VBR 50kbps", "Opus VBR 70kbps", "Opus VBR 160kbps", "AAC 48kbps", "AAC 128kbps"]
SUB_LANGS   = ["en", "no"]
DEFAULT_AUDIO = "Opus VBR 70kbps"
DEFAULT_VIDEO = "MP4 720p"
DEFAULT_LANG  = "en"
STREAMING_PATTERNS = ["yt.com", "twitch.com"]


class AgeRestrictedError(Exception):
    pass


def check_stream(url: str) -> bool:
    if ".m3u8" in url.lower():
        for p in STREAMING_PATTERNS:
            if p in url.lower():
                return True
    return False


def is_hls(f: str) -> bool:
    if len(f.split("hls-")) == 2:
        try:
            int(f.split("hls-")[1])
        except ValueError:
            try:
                int(f.split("-")[1])
            except ValueError:
                return False
        return True
    return False

def height_to_width(h: int) -> int:
    if h > 720 and h <= 1080:
        return 1920
    if h > 576 and h <= 720:
        return 1280
    if h > 480 and h <= 576:
        return 720
    if h > 360 and h <= 480:
        return 640
    if h > 240 and h <= 360:
        return 480
    if h <= 240:
        return 360
    return h

def valid_youtube_url(url: str) -> bool:
    if not len(url.split(".")) > 1:
        return False
    return True


def get_source_links(url: str) -> str:
    headers = {'Accept-Encoding': 'identity'}

    if "://t.me" in url and not "embed=1" in url:
        url += "?embed=1"

    try:
        r = requests.get(url, headers=headers)
    except:
        log.error("Unable to download page?!")
        return []
    html = r.text
    elements = re.findall(r'[\'"]?([^\'" >]+)', html)
    urls = []

    if "://t.me" in url:
        if "grouped_media" in html:
            log.error("Multiple videos, link individual Telegram page!")
            return []

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

    return urls


def get_content_info(url: str) -> dict:
    if url.lower().endswith(".mp4"):
        return {
            "video_formats": {"source": {"url": url, "dimensions": (0, 0)}},
            "audio_formats": {},
            "sub_formats": {},
            "duration": 0.0,
            "thumbnail": "",
            "title": "No title (mp4)"
        }
    vid_ids = {YT_FORMATS[k]: k for k in VID_FORMATS}
    aud_ids = {YT_FORMATS[k]: k for k in AUD_FORMATS}
    d = {
        "video_formats": {},
        "audio_formats": {},
        "sub_formats": {},
        "duration": 0.0,
        "thumbnail": "",
        "title": ""
    }

    log.info("Fetching data from YouTube link...")
    ydl = youtube_dl.YoutubeDL({
        "cookiefile": program_path("cookies.txt"),
        "subtitleslang": SUB_LANGS,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "write_all_thumbnails": True,
        "noplaylist": True
    })

    video = None

    with ydl:
        try:
            result = ydl.extract_info(
                url,
                download=False
            )
        except youtube_dl.utils.DownloadError as e:
            log.error("Error during fetching of video info, doing manual")
            video = None
        else:
            if "entries" in result:
                video = result["entries"][0]
            else:
                video = result

    if not video:
        urls = get_source_links(url)
        if len(urls):
            log.info("Found urls in source code.")
            log.info(urls)
            url = urls[-1]  # Guessing last is highest quality lol
            return {
                "video_formats": {"source": {"url": url, "dimensions": (0, 0)}},
                "audio_formats": {},
                "sub_formats": {},
                "duration": 0.0,
                "thumbnail": "",
                "title": "No title (mp4)"
            }

        log.error("Was not able to find a video on the url given.")
        return d

    else:
        if "thumbnail" in video:
            d["thumbnail"] = video["thumbnail"]
        if "title" in video:
            d["title"] = video["title"]

        if "requested_subtitles" in video:
            try:
                for lang, sub in video["requested_subtitles"].items():
                    if lang in SUB_LANGS:
                        d["sub_formats"][lang] = sub["url"]
            except AttributeError:
                pass

        try:
            d["duration"] = float(video["duration"])
        except (ValueError, KeyError):
            log.error("There's no duration in info from YouTube.")
            pass

        # for f in video["formats"]:
        #     if "vcodec" in f.keys():
        #         print(f["vcodec"])
        #     else:
        #         print(f["format"])
        # print(video["formats"])

        for u in [f for f in video["formats"]]:
            if "url" in u:
                if check_stream(u["url"]):
                    continue
            try:
                x = int(u["width"])
                y = int(u["height"])
            except (KeyError, TypeError):
                try:
                    y = int(u["height"])
                    x = height_to_width(y)
                except (KeyError, TypeError):
                    x, y = 0, 0

            if "vcodec" in u.keys():
                if u["format_id"] in vid_ids.keys():
                    d["video_formats"][vid_ids[u["format_id"]]] = {"url": u["url"], "dimensions": (x, y)}
                elif is_hls(u["format_id"]):
                    d["video_formats"][u["format"]] = {"url": u["url"], "dimensions": (x, y)}
                else:
                    try:
                        int(u["format_id"])
                    except ValueError:
                        pass
                    else:
                        d["video_formats"][u["format"]] = {"url": u["url"], "dimensions": (x, y)}
            elif "ext" in u.keys():
                if u["ext"] == "mp4":
                    if u["format_id"] in vid_ids.keys():
                        d["video_formats"][vid_ids[u["format_id"]]] = {"url": u["url"], "dimensions": (x, y)}

            #print(u["format"], u["format_id"])
            if "acodec" in u.keys():
                if u["format_id"] in aud_ids.keys():
                    d["audio_formats"][aud_ids[u["format_id"]]] = u["url"]
                elif u["acodec"] != None:
                    print(u["acodec"])
            elif "audio" in u["format"]:
                if u["format_id"] in aud_ids.keys():
                    d["audio_formats"][aud_ids[u["format_id"]]] = u["url"]

    if not len(d["video_formats"]):
        log.warning("Last ditch attempt to get video link.")
        urls = get_source_links(url)
        if len(urls):
            url = urls[-1]  # Guessing last is highest quality lol
            return {
                "video_formats": {"source": {"url": url, "dimensions": (0, 0)}},
                "audio_formats": {},
                "sub_formats": {},
                "duration": 0.0,
                "thumbnail": "",
                "title": "No title (mp4)"
            }

        for v in video["formats"]:
            try:
                print(str(v["format"]) + "   " + str(v["format_id"]) + "  " + str(v["vcodec"]))
            except:
                continue
        
    return d


if __name__ == "__main__":

    print("=================================")
    print(get_content_info("https://www.youtube.com/watch?v=AndsdQO0Wmk"))
    print("=================================")
