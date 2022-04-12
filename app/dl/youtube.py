from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError
import logging
from .helpers import program_path, height_to_width, fix_youtube_shorts, fix_reddit_old, check_stream, \
    is_dash, is_hls, is_avc, is_streaming_site, remove_links

from .metadata import get_source_links, find_highest_quality_url, strip_useless

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
    "discord:", "independent journalism", "made possible by supporters", "by patreon",
]


class AgeRestrictedError(Exception):
    pass


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
        # if "description" in video:
        #     desc = video["description"]
        #     desc = remove_links(desc)
        #     desc_segs = desc.split("\n")
        #     ok = []
        #     for ds in desc_segs:
        #         if any(x in ds.lower() for x in AD_DESCRIPTIONS):
        #             continue
        #         elif ds.count("#") > 4:
        #             continue
        #
        #         ok.append(ds)
        #
        #
        #     desc = "\n".join(ok)
        #     desc = strip_useless(desc)
        #
        #     d["title"] = desc
        #     if "title" in video:
        #         d["title"] = video["title"] + "\n" + d["title"]
        #     d["title"] = d["title"][:512]
        #
        # el
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
                        if is_hls(u["format_id"]) or is_dash(u["format_id"]) or is_avc(u["format_id"]):
                            video_id_found = u["format_id"]
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
                        elif is_hls(u["format_id"]) or is_dash(u["format_id"]) or is_avc(u["format_id"]):
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
                "title": title
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

            if "title" in video:
                desc = video["title"] + "\n" + desc
            desc = desc[:1024]

        elif "title" in video:
            desc = video["title"]

    desc = strip_useless(desc)
    return desc


if __name__ == "__main__":

    print("=================================")
    print(get_content_info("https://www.youtube.com/watch?v=AndsdQO0Wmk"))
    print("=================================")
