#from youtube_dl import YoutubeDL
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError
#from youtube_dl.utils import DownloadError
from html import unescape
import logging
import re
import requests
import codecs
from urllib.parse import urlencode, urlparse, urlunparse, parse_qs
from .helpers import program_path, find_between

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
    "Vimeo 360p0", "Vimeo 360p1", "Vimeo 480p0", "Vimeo 640p0", "Vimeo 720p0",  "Vimeo 1080p0"
]
AUD_FORMATS = ["HE-AAC", "AAC-LC", "MP3", "HLS audio 0", "HLS audio 1", "Opus VBR 50kbps", "Opus VBR 70kbps", "Opus VBR 160kbps", "AAC 48kbps", "AAC 128kbps"]
SUB_LANGS   = ["en", "no"]
DEFAULT_AUDIO = "Opus VBR 70kbps"
DEFAULT_VIDEO = "MP4 720p"
DEFAULT_LANG  = "en"
STREAMING_PATTERNS = ["yt.com", "twitch.com", "youtube.com", "youtu.be"]

DISPOSABLE_QUERIES = [
    "ref", "ref_src", "ref_url", "taid",
    "fbclid", "gclid", "gclsrc",
    "utm_campaign", "utm_medium", "utm_source", "utm_content", "utm_term", "utm_id",
    "_ga", "mc_cid", "mc_eid", "usg", "esrc", "ved",
    "__cft__[0]", "__cft__", "__tn__",
    "__mk_de_DE", "__mk_en_US", "__mk_en_GB", "__mk_nb_NO",
    "rnid", "pf_rd_r", "pf_rd_p", "pd_rd_i", "pd_rd_r", "pd_rd_wg",
    "_bta_tid", "_bta_c", "trk_contact", "trk_msg", "trk_module", "trk_sid",
    "gdfms", "gdftrk", "gdffi", "_ke",
    "redirect_log_mongo_id", "redirect_mongo_id", "sb_referer_host",
    "mkwid", "pcrid", "ef_id", "s_kwcid", "msclkid", "dm_i", "epik",
    "pk_campaign", "pk_kwd", "pk_keyword", "piwik_campaign", "piwik_kwd", "piwik_keyword",
    "mtm_campaign", "mtm_keyword", "mtm_source", "mtm_medium", "mtm_content",
    "mtm_cid", "mtm_group", "mtm_placement",
    "matomo_campaign", "matomo_keyword", "matomo_source", "matomo_medium", "matomo_content",
    "matomo_cid", "matomo_group", "matomo_placement", "_branch_match_id",
    "hsa_cam", "hsa_grp", "hsa_mt", "hsa_src", "hsa_ad", "hsa_acc", "hsa_net", "hsa_kw", "hsa_tgt", "hsa_ver",
    "ns_mchannel", "ns_source", "ns_campaign", "ns_linkname", "ns_fee",
    "pinned_post_locator", "pinned_post_asset_id", "pinned_post_type",
    "ab_channel"
]
TIME_QUERIES = [
    "s", "t", "time", "seek"
]
TIME_LOCATIONS = [
    "twitter.com", "youtube.com", "t.co", "youtu.be", "nrk.no"
]


class AgeRestrictedError(Exception):
    pass


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


def check_stream(url: str) -> bool:
    if ".m3u8" in url.lower():
        return is_streaming_site(url)
    return False


def is_streaming_site(url: str) -> bool:
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
    if len(f.split("hls_1080p-")) == 2 or len(f.split("hls_720p-")) == 2:
        if "1080p" in f:
            try:
                int(f.split("hls_1080p-")[1])
            except ValueError:
                return False
        elif "720p" in f:
            try:
                int(f.split("hls_720p-")[1])
            except ValueError:
                return False
        return True
    return False


def is_dash(format: str) -> bool:
    if not isinstance(format, str) and not len(format):
        return False
    if len(format.split("v")) == 2:
        try:
            int(len(format.split("v")[0]))
        except (ValueError, TypeError):
            pass
        else:
            return True
    return False


def is_avc(format: str) -> bool:
    if not isinstance(format, str) and not len(format):
        return False
    if len(format.split("avc1.")) == 2:
        try:
            assert len(format.split("avc1.")[1]) == 6
        except AssertionError:
            return False
        else:
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


def valid_video_url(url: str) -> bool:
    if not url or not isinstance(url, str):
        return False

    u = urlparse(url)

    if u.scheme not in ["http", "https", "ftp"]:
        return False

    return True


def fix_youtube_shorts(url: str) -> str:
    if "youtube.com/shorts/" in url:
        return url.replace("/shorts/", "/embed/")
    return url


def minimize_url(url: str) -> str:
    u = urlparse(url)
    if len(u.query):
        query = parse_qs(u.query, keep_blank_values=True)
        for dq in DISPOSABLE_QUERIES:
            query.pop(dq, None)
        if u.netloc.replace("www.", "") in TIME_LOCATIONS:
            for dq in TIME_QUERIES:
                query.pop(dq, None)

        u = u._replace(query=urlencode(query, True))

    return urlunparse(u)


def get_og_tags(html: str, title_only=False):
    titles = re.findall(r"<meta [^>]*property=[\"']og:title[\"'] [^>]*content=[\"']([^'^\"]+?)[\"'][^>]*>", html)
    if title_only:
        return [unescape(t) for t in titles]
    descs = re.findall(r"<meta [^>]*property=[\"']og:description[\"'] [^>]*content=[\"']([^'^\"]+?)[\"'][^>]*>", html)
    names = re.findall(r"<meta [^>]*property=[\"']og:site_name[\"'] [^>]*content=[\"']([^'^\"]+?)[\"'][^>]*>", html)
    return [unescape(t) for t in titles] + [unescape(t) for t in descs] + [unescape(t) for t in names]


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
            else:
                title = "No title (mp4)"

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


def get_content_info(url: str) -> dict:
    log.info(f"Attempting to gather content info for {url}")
    if url.lower().endswith(".mp4"):
        log.debug(f"It's a direct mp4 link, that's nice.")
        return {
            "video_formats": {"source": {"url": url, "dimensions": (0, 0)}},
            "audio_formats": {},
            "sub_formats": {},
            "duration": 0.0,
            "thumbnail": "",
            "title": "No title (mp4)"
        }
    url = fix_youtube_shorts(url)
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
    ydl = YoutubeDL({
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
                "video_formats": {"source": {"url": url, "dimensions": (0, 0)}},
                "audio_formats": {},
                "sub_formats": {},
                "duration": 0.0,
                "thumbnail": "",
                "title": title
            }

        log.error("Was not able to find a video on the url given.")
        return d

    else:
        log.debug(f"YoutubeDL found a video.")
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

        if not d["duration"] > 0:
            if any(u in url for u in ["googlevideo.com", "youtube.com", "www.youtube.com", "y2u.be", "://youtu.be", "twitch.com"]):
                log.warning("Nope, not downloading current streams.")
                return d

        if "formats" not in video:
            log.debug(video)
            log.error("No format key in video.")
        else:
            for u in [f for f in video["formats"]]:
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
                        d["video_formats"][vid_ids[u["format_id"]]] = {"url": u["url"], "dimensions": (x, y)}
                    elif not is_streaming_site(url):
                        if is_hls(u["format_id"]) or is_dash(u["format_id"]) or is_avc(u["format_id"]):
                            d["video_formats"][u["format"]] = {"url": u["url"], "dimensions": (x, y)}
                        else:
                            try:
                                int(u["format_id"])
                            except ValueError:
                                pass
                            else:
                                d["video_formats"][u["format"]] = {"url": u["url"], "dimensions": (x, y)}
                    elif u["vcodec"] != "none":
                        log.error(f'Unhandled video codec: {u["format_id"]} {u["vcodec"]} {u["format"]}')

                elif "ext" in u.keys() or "video_ext" in u.keys():
                    if u["video_ext"] in ["mp4", "ogv"] or u["ext"] in ["mp4", "ogv"]:
                        if u["format_id"] in vid_ids.keys():
                            d["video_formats"][vid_ids[u["format_id"]]] = {"url": u["url"], "dimensions": (x, y)}
                        elif is_hls(u["format_id"]) or is_dash(u["format_id"]) or is_avc(u["format_id"]):
                            d["video_formats"][u["format"]] = {"url": u["url"], "dimensions": (x, y)}

                if "acodec" in u.keys():
                    if u["format_id"] in aud_ids.keys():
                        d["audio_formats"][aud_ids[u["format_id"]]] = u["url"]
                    elif u["acodec"] is not None:
                        if u["acodec"] in aud_ids.keys():
                            d["audio_formats"][aud_ids[u["acodec"]]] = u["url"]
                        elif u["acodec"] != "none":
                            log.error(f'Unhandled audio codec: {u["format_id"]}')
                elif "audio" in u["format"]:
                    if u["format_id"] in aud_ids.keys():
                        d["audio_formats"][aud_ids[u["format_id"]]] = u["url"]

    if not len(d["video_formats"]):
        log.warning("Last ditch attempt to get video link.")
        title, urls = get_source_links(url)
        if len(urls):
            url = find_highest_quality_url(urls)

            return {
                "video_formats": {"source": {"url": url, "dimensions": (0, 0)}},
                "audio_formats": {},
                "sub_formats": {},
                "duration": 0.0,
                "thumbnail": "",
                "title": title
            }
        if video:
            if "formats" in video:
                for v in video["formats"]:
                    try:
                        print(str(v["format"]) + "   " + str(v["format_id"]) + "  " + str(v["vcodec"]))
                    except:
                        continue
    else:
        log.info(f"Found {len(d['video_formats'])} video streams.")
        log.info(f"Found {len(d['audio_formats'])} separate audio streams.")

    return d


if __name__ == "__main__":

    print("=================================")
    print(get_content_info("https://www.youtube.com/watch?v=AndsdQO0Wmk"))
    print("=================================")
