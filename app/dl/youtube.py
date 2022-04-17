from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError
from datetime import datetime
import time
import logging
from .helpers import program_path, height_to_width, fix_youtube_shorts, fix_reddit_old, check_stream, \
    is_dash, is_hls, is_avc, is_streaming_site, remove_links, is_http

from .metadata import get_source_links, find_highest_quality_url, strip_useless, clean_description

log = logging.getLogger("posterity_dl.yt")

YT_FORMATS = {
    "YT 1080p60": "299",
    "YT 1080p": "137",
    "YT 720p": "136",
    "YT 720p2": "95",
    "YT 640p": "93",
    "YT 480p": "135",
    "YT 360p": "134",
    "YT 240p": "133",
    "VP9 1080p": "248",
    "VP9 720p": "247",
    "VP9 480p": "244",
    "VP9 360p": "243",
    "VP9 240p": "242",
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
    "AAC-LC": "mp4a.40.2",
    "HE-AAC": "mp4a.40.5",
    "MP3": "mp4a.40.34",
    "HLS audio 0": "hls-0-audio_0",
    "HLS audio 1": "hls-1-audio_0",
    "Vimeo 360p0": "http-360p-0",
    "Vimeo 360p1": "http-360p-1",
    "Vimeo 480p0": "http-480p-0",
    "Vimeo 640p0": "http-640p-0",
    "Vimeo 720p0": "http-720p-0",
    "Vimeo 1080p0": "http-1080p-0",
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
    "YT 1080p", "YT 1080p60", "YT 720p", "YT 720p2", "YT 640p", "YT 480p", "YT 360p", "YT 240p",
    "MP4 720p", "MP4 360p", "MP4 240p", "MP4 576p",
    "MP4 720p 4:3", "MP4 640p 4:3", "MP4 360p 4:3", "MP4 240p 4:3", "MP4 180p 4:3", "MP4 Mobile",
    "Vimeo 360p0", "Vimeo 360p1", "Vimeo 480p0", "Vimeo 640p0", "Vimeo 720p0",  "Vimeo 1080p0",
    "VP9 240p", "VP9 360p", "VP9 480p", "VP9 720p", "VP9 1080p"
]
AUD_FORMATS = ["HE-AAC", "AAC-LC", "MP3", "HLS audio 0", "HLS audio 1", "Opus VBR 50kbps", "Opus VBR 70kbps", "Opus VBR 160kbps", "AAC 48kbps", "AAC 128kbps"]
SUB_LANGS   = ["en", "no"]
DEFAULT_AUDIO = "Opus VBR 70kbps"
DEFAULT_VIDEO = "MP4 720p"
DEFAULT_LANG  = "en"


class AgeRestrictedError(Exception):
    pass


def get_content_info(url: str) -> dict:
    log.info(f"Attempting to gather content info for {url}")
    if url.lower().endswith(".mp4"):
        log.debug(f"It's a direct mp4 link, that's nice.")
        return {
            "video_formats": {"source": {"url": url, "dimensions": (0, 0), "audio": True}},
            "audio_formats": {},
            "sub_formats": {},
            "duration": 0.0,
            "thumbnail": "",
            "title": "No title (mp4)",
            "upload_date": time.mktime(datetime.now().timetuple())
        }
    url = fix_youtube_shorts(url)
    url = fix_reddit_old(url)
    vid_ids = {YT_FORMATS[k]: k for k in VID_FORMATS}
    aud_ids = {YT_FORMATS[k]: k for k in AUD_FORMATS}
    d = {
        "video_formats": {},
        "audio_formats": {},
        "sub_formats": {},
        "duration": 0.0,
        "thumbnail": "",
        "title": "",
        "upload_date": time.mktime(datetime.now().timetuple())
    }

    log.info("Fetching data from YouTube link...")
    ydl = YoutubeDL({
        "cookiefile": program_path("cookies.txt"),
        "subtitleslang": SUB_LANGS,
        "writesubtitles": True,
        "writeautomaticsub": True,
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
        log.debug(f"YoutubeDL failed to find a video, let's see what we can do with it.")
        title, urls = get_source_links(url)
        if len(urls):
            log.info("Found urls in source code.")

            url = find_highest_quality_url(urls)

            return {
                "video_formats": {"source": {"url": url, "dimensions": (0, 0), "audio": True}},
                "audio_formats": {},
                "sub_formats": {},
                "duration": 0.0,
                "thumbnail": "",
                "title": title,
                "upload_date": time.mktime(datetime.now().timetuple())
            }

        log.error("Was not able to find a video on the url given.")
        return d

    else:
        # [
        #   'id', 'title', 'formats', 'thumbnails', 'thumbnail',
        #   'description', 'uploader', 'uploader_id', 'uploader_url',
        #   'channel_id', 'channel_url', 'duration', 'view_count',
        #   'average_rating', 'age_limit', 'webpage_url', 'categories',
        #   'tags', 'playable_in_embed', 'is_live', 'was_live', 'live_status',
        #   'release_timestamp', 'automatic_captions', 'subtitles', 'chapters',
        #   'upload_date', 'like_count', 'channel', 'channel_follower_count',
        #   'availability', 'original_url', 'webpage_url_basename',
        #   'webpage_url_domain', 'extractor', 'extractor_key', 'playlist',
        #   'playlist_index', 'display_id', 'fulltitle', 'duration_string',
        #   'requested_subtitles', '__has_drm', 'requested_formats', 'format',
        #   'format_id', 'ext', 'protocol', 'language', 'format_note',
        #   'filesize_approx', 'tbr', 'width', 'height', 'resolution', 'fps',
        #   'dynamic_range', 'vcodec', 'vbr', 'stretched_ratio', 'acodec', 'abr', 'asr'
        # ]
        log.debug(f"YoutubeDL found a video.")
        if "thumbnail" in video:
            d["thumbnail"] = video["thumbnail"]
        if "description" in video:
            desc = video["description"]
            d["title"] = clean_description(desc)

        elif "title" in video:
            d["title"] = clean_description(video["title"])

        if "tags" in video and len(video["tags"]):
            d["title"] += "\n" + ", ".join(video["tags"])
        if "categories" in video and len(video["categories"]):
            d["title"] += "\n" + ", ".join(video["categories"])


        if "release_timestamp" in video and video["release_timestamp"]:
            print(video["release_timestamp"])
            print("TIMESTAMP!!!!!")
        if "upload_date" in video and video["upload_date"]:
            t = datetime.strptime(video["upload_date"], "%Y%m%d")
            d["upload_date"] = time.mktime(t.timetuple())
        else:
            d["upload_date"] = time.mktime(datetime.now().timetuple())

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

        if not d["duration"] > 0:
            if any(u in url for u in ["googlevideo.com", "youtube.com", "www.youtube.com", "y2u.be", "://youtu.be", "twitch.com"]):
                log.warning("Nope, not downloading current streams.")
                return d

        if "formats" not in video:
            log.error("No format key in video.")
        else:
            for u in [f for f in video["formats"]]:
                video_id_found = ""
                if "url" in u:
                    if check_stream(u["url"]):
                        log.error("This link was a stream (?): " + u["url"])
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
                        video_id_found = u["format_id"]
                        d["video_formats"][vid_ids[u["format_id"]]] = {"url": u["url"], "dimensions": (x, y), "audio": False}
                    elif not is_streaming_site(url):
                        if is_http(u["format_id"]) or is_hls(u["format_id"]) or is_dash(u["format_id"]) or is_avc(u["format_id"]):
                            video_id_found = u["format_id"]
                            if is_http(u["format_id"]):
                                d["video_formats"][u["format"]] = {"url": u["url"], "dimensions": (x, y), "audio": True}
                            else:
                                d["video_formats"][u["format"]] = {"url": u["url"], "dimensions": (x, y), "audio": False}
                        else:
                            try:
                                int(u["format_id"])
                            except ValueError:
                                pass
                            else:
                                d["video_formats"][u["format"]] = {"url": u["url"], "dimensions": (x, y), "audio": False}
                    elif u["vcodec"] != "none":
                        log.error(f'Unhandled video codec: {u["format_id"]} {u["vcodec"]} {u["format"]}')

                elif "ext" in u.keys() or "video_ext" in u.keys():
                    if u["video_ext"] in ["mp4", "ogv"] or u["ext"] in ["mp4", "ogv"]:
                        if u["format_id"] in vid_ids.keys():
                            video_id_found = u["format_id"]
                            d["video_formats"][vid_ids[u["format_id"]]] = {"url": u["url"], "dimensions": (x, y), "audio": False}
                        elif is_http(u["format_id"]) or is_hls(u["format_id"]) or is_dash(u["format_id"]) or is_avc(u["format_id"]):
                            video_id_found = u["format_id"]
                            d["video_formats"][u["format"]] = {"url": u["url"], "dimensions": (x, y), "audio": False}

                if "acodec" in u.keys() and video_id_found:
                    try:
                        d["video_formats"][video_id_found]["audio"] = True
                        continue
                    except KeyError:
                        pass

                if "acodec" in u.keys():
                    if u["format_id"] in aud_ids.keys():
                        d["audio_formats"][aud_ids[u["format_id"]]] = u["url"]
                    elif u["acodec"] is not None:
                        if u["acodec"] in aud_ids.keys():
                            d["audio_formats"][aud_ids[u["acodec"]]] = u["url"]
                        elif u["acodec"] != "none":
                            log.error(f'Unhandled audio codec: {u["format_id"]}')
                elif "audio" in u["format"] and not video_id_found:
                    if u["format_id"] in aud_ids.keys():
                        d["audio_formats"][aud_ids[u["format_id"]]] = u["url"]

    if not len(d["video_formats"]):
        log.warning("Last ditch attempt to get video link.")
        title, urls = get_source_links(url)
        if len(urls):
            url = find_highest_quality_url(urls)

            return {
                "video_formats": {"source": {"url": url, "dimensions": (0, 0), "audio": True}},
                "audio_formats": {},
                "sub_formats": {},
                "duration": 0.0,
                "thumbnail": "",
                "title": title,
                "upload_date": time.mktime(datetime.now().timetuple())
            }
        if video:
            if "formats" in video:
                for v in video["formats"]:
                    try:
                        print(str(v["format"]) + "   " + str(v["format_id"]) + "  " + str(v["vcodec"]))
                    except:
                        print(v)
                        continue
    else:
        log.info(f"Found {len(d['video_formats'])} video streams.")
        log.info(f"Found {len(d['audio_formats'])} separate audio streams.")

    return d


if __name__ == "__main__":

    print("=================================")
    print(get_content_info("https://www.youtube.com/watch?v=AndsdQO0Wmk"))
    print("=================================")

#
# [
#     {
#         'format_id': 'hls-288',
#         'format_index': None,
#         'url': 'https://video.twimg.com/amplify_video/1507863263668748288/pl/480x270/fAtBxreSuYgh6ZOn.m3u8?container=fmp4', 'manifest_url': 'https://video.twimg.com/amplify_video/1507863263668748288/pl/1wYOS01EuAVRitch.m3u8?tag=14&container=fmp4', 'tbr': 288.0, 'ext': 'mp4', 'fps': None, 'protocol': 'm3u8_native', 'preference': None, 'quality': None, 'width': 480, 'height': 270, 'vcodec': 'avc1.4d001e', 'acodec': 'mp4a.40.2', 'dynamic_range': 'SDR', 'video_ext': 'mp4', 'audio_ext': 'none', 'vbr': 288.0, 'abr': 0.0, 'format': 'hls-288 - 480x270',
#         'resolution': '480x270',
#         'filesize_approx': 2773647.36,
#         'http_headers': {
#             'User-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
#             'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
#             'Accept-encoding': 'gzip, deflate, br',
#             'Accept-language': 'en-us,en;q=0.5',
#             'Sec-fetch-mode': 'navigate'
#         }
#     }, {
#         'url': 'https://video.twimg.com/amplify_video/1507863263668748288/vid/480x270/AYotHadA0tE0Y-Gi.mp4?tag=14',
#         'format_id': 'http-288',
#         'tbr': 288,
#         'width': 480,
#         'height': 270,
#         'protocol': 'https',
#         'ext': 'mp4',
#         'video_ext': 'mp4',
#         'audio_ext': 'none',
#         'vbr': 288, 'abr': 0,
#         'format': 'http-288 - 480x270',
#         'resolution': '480x270',
#         'dynamic_range':'SDR',
#         'filesize_approx': 2773647.36,
#         'http_headers': {
#             'User-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
#             'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
#             'Accept-encoding': 'gzip, deflate, br',
#             'Accept-language': 'en-us,en;q=0.5',
#             'Sec-fetch-mode': 'navigate'
#         }
#     }, {
#         'format_id': 'hls-832',
#         'format_index': None,
#         'url': 'https://video.twimg.com/amplify_video/1507863263668748288/pl/640x360/b4am5XambTJ62AfU.m3u8?container=fmp4',
#         'manifest_url': 'https://video.twimg.com/amplify_video/1507863263668748288/pl/1wYOS01EuAVRitch.m3u8?tag=14&container=fmp4',
#         'tbr': 832.0,
#         'ext': 'mp4',
#         'fps': None,
#         'protocol': 'm3u8_native',
#         'preference': None,
#         'quality': None,
#         'width': 640,
#         'height': 360,
#         'vcodec': 'avc1.4d001f',
#         'acodec': 'mp4a.40.2',
#         'dynamic_range': 'SDR',
#         'video_ext': 'mp4',
#         'audio_ext': 'none',
#         'vbr': 832.0,
#         'abr': 0.0,
#         'format': 'hls-832 - 640x360',
#         'resolution': '640x360',
#         'filesize_approx': 8012759.039999999,
#         'http_headers': {
#             'User-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
#             'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
#             'Accept-encoding': 'gzip, deflate, br',
#             'Accept-language': 'en-us,en;q=0.5',
#             'Sec-fetch-mode': 'navigate'
#         }
#     }, {
#         'url': 'https://video.twimg.com/amplify_video/1507863263668748288/vid/640x360/vKzkUBwDZZOZz68Y.mp4?tag=14',
#         'format_id': 'http-832',
#         'tbr': 832,
#         'width': 640,
#         'height': 360,
#         'protocol': 'https',
#         'ext': 'mp4',
#         'video_ext': 'mp4',
#         'audio_ext': 'none',
#         'vbr': 832,
#         'abr': 0,
#         'format': 'http-832 - 640x360',
#         'resolution': '640x360',
#         'dynamic_range': 'SDR',
#         'filesize_approx': 8012759.039999999,
#         'http_headers': {
#             'User-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36', 'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8', 'Accept-encoding': 'gzip, deflate, br', 'Accept-language': 'en-us,en;q=0.5', 'Sec-fetch-mode': 'navigate'}}, {'format_id': 'hls-2176', 'format_index': None, 'url': 'https://video.twimg.com/amplify_video/1507863263668748288/pl/1280x720/jRaNYws_hWK5Hc9W.m3u8?container=fmp4', 'manifest_url': 'https://video.twimg.com/amplify_video/1507863263668748288/pl/1wYOS01EuAVRitch.m3u8?tag=14&container=fmp4', 'tbr': 2176.0, 'ext': 'mp4', 'fps': None, 'protocol': 'm3u8_native', 'preference': None, 'quality': None, 'width': 1280, 'height': 720, 'vcodec': 'avc1.640020', 'acodec': 'mp4a.40.2', 'dynamic_range': 'SDR', 'video_ext': 'mp4', 'audio_ext': 'none', 'vbr': 2176.0, 'abr': 0.0, 'format': 'hls-2176 - 1280x720', 'resolution': '1280x720', 'filesize_approx': 20956446.72, 'http_headers': {'User-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36', 'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8', 'Accept-encoding': 'gzip, deflate, br', 'Accept-language': 'en-us,en;q=0.5', 'Sec-fetch-mode': 'navigate'}}, {'url': 'https://video.twimg.com/amplify_video/1507863263668748288/vid/1280x720/huTzhl3CuOrmltWl.mp4?tag=14', 'format_id': 'http-2176', 'tbr': 2176, 'width': 1280, 'height': 720, 'protocol': 'https', 'ext': 'mp4', 'video_ext': 'mp4', 'audio_ext': 'none', 'vbr': 2176, 'abr': 0, 'format': 'http-2176 - 1280x720', 'resolution': '1280x720', 'dynamic_range': 'SDR', 'filesize_approx': 20956446.72, 'http_headers': {'User-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
#             'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
#             'Accept-encoding': 'gzip, deflate, br',
#             'Accept-language': 'en-us,en;q=0.5', 'Sec-fetch-mode': 'navigate'
#         }
#     }
# ]