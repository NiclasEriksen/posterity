import os
import sys
import math
import re
import shortuuid
from html import unescape
from datetime import datetime
from urllib.parse import urlencode, urlparse, urlunparse, parse_qs

TIME_QUERIES = [
    "s", "t", "time", "seek", "context", "feature"
]

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
TIME_LOCATIONS = [
    "twitter.com", "youtube.com", "t.co", "youtu.be", "nrk.no", "reddit.com", "redd.it"
]


def unique_filename() -> str:
    return datetime.now().strftime("%y%m%d-%H%M%S") + "-" + shortuuid.uuid()[:5]


def remove_links(s: str) -> str:
    return re.sub(r'https?://\S+', "", s)


def find_between(s, first, last):
    try:
        start = s.index( first ) + len( first )
        end = s.index( last, start )
        return s[start:end]
    except ValueError:
        return ""


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


def convert_file_size(size_bytes):
    if size_bytes == 0:
        return "0B"
    size_name = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return "%s %s" % (s, size_name[i])


def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)


def program_path(relative_path):
    if getattr(sys, 'frozen', False):
        application_path = os.path.dirname(sys.executable)
    else:
        application_path = os.path.dirname(__file__)
    return os.path.join(application_path, relative_path)


def seconds_to_time(s: float) -> (int, int, float):
    return (int(s) // 3600, int(s % 3600) // 60, s % 3600.0 % 60.0) 


def time_to_seconds(h: int = 0, m: int = 0, s: float = 0.0) -> float:
    return float(h * 3600 + m * 60 + s)


def seconds_to_verbose_time(t: float) -> str:
    hours, rem = divmod(t, 3600)
    minutes, seconds = divmod(rem, 60)
    hours, minutes, seconds = int(hours), int(minutes), int(seconds)

    if hours > 1:
        if minutes > 1:
            return f"{hours} hrs, {minutes} mins"
        elif minutes > 0:
            return f"{hours} hrs, 1 min"
        return f"{hours} hours"
    elif hours > 0:
        if minutes > 1:
            return f"1 hour, {minutes} minutes"
        elif minutes > 0:
            return f"1 hour, 1 minute"
        return "1 hour"
    else:
        if minutes > 1:
            if seconds > 1:
                return f"{minutes} minutes, {seconds} seconds"
            elif seconds > 0:
                return f"{minutes} minutes, 1 second"
            return f"{minutes} minutes"
        elif minutes > 0:
            if seconds > 1:
                return f"1 minute, {seconds} seconds"
            elif seconds > 0:
                return "1 minute, 1 second"
            return "1 minute"
        else:
            if seconds > 1:
                return f"{seconds} seconds"
            elif seconds > 0:
                return "1 second"
            return "0 seconds"


def map_range(x: float, a1: float, a2: float, b1: float, b2: float) -> float:
    try:
        return (x - a1) / (a2 - a1) * (b2 - b1) + b1
    except ZeroDivisionError:
        return b1


def remove_emoji(data: str):
    emoj = re.compile("["
                      u"\U0001F600-\U0001F64F"  # emoticons
                      u"\U0001F300-\U0001F5FF"  # symbols & pictographs
                      u"\U0001F680-\U0001F6FF"  # transport & map symbols
                      u"\U0001F1E0-\U0001F1FF"  # flags (iOS)
                      u"\U00002500-\U00002BEF"  # chinese char
                      u"\U00002702-\U000027B0"
                      u"\U00002702-\U000027B0"
                      u"\U000024C2-\U0001F251"
                      u"\U0001f926-\U0001f937"
                      u"\U00010000-\U0010ffff"
                      u"\u2640-\u2642"
                      u"\u2600-\u2B55"
                      u"\u200d"
                      u"\u23cf"
                      u"\u23e9"
                      u"\u231a"
                      u"\ufe0f"  # dingbats
                      u"\u3030"
                      "]+", re.UNICODE)
    return re.sub(emoj, '', data)


def seconds_to_hhmmss(t: float) -> str:
    hours, rem = divmod(t, 3600)
    minutes, seconds = divmod(rem, 60)
    hours, minutes, seconds = int(hours), int(minutes), int(seconds)

    if hours > 0:
        return f"{hours}h{minutes}m{seconds}s"
    elif minutes > 0:
        return f"{minutes}m{seconds}s"
    elif seconds > 0:
        return f"{seconds}s"
    else:
        return "Unknown"


def to_ms(string: str = None, precision: int = None, **kwargs) -> float:
    """
    Convert a string to milliseconds.
    You can either pass a string, or a set of keyword args ("hour", "min", "sec", "ms") to convert.
    If "precision" is set, the result is rounded to the number of decimals given.
    From: https://gist.github.com/Hellowlol/5f8545e999259b4371c91ac223409209
    """
    if string:
        hour = int(string[0:2])
        minute = int(string[3:5])
        sec = int(string[6:8])
        ms = int(string[10:11])
    else:
        hour = int(kwargs.get("hour", 0))
        minute = int(kwargs.get("min", 0))
        sec = int(kwargs.get("sec", 0))
        ms = int(kwargs.get("ms", 0))

    result = (hour * 60 * 60 * 1000) + (minute * 60 * 1000) + (sec * 1000) + ms
    if precision and isinstance(precision, int):
        return round(result, precision)
    return result


def reverse_readline(filename, buf_size=8192):
    """A generator that returns the lines of a file in reverse order"""
    with open(filename) as fh:
        segment = None
        offset = 0
        fh.seek(0, os.SEEK_END)
        file_size = remaining_size = fh.tell()
        while remaining_size > 0:
            offset = min(file_size, offset + buf_size)
            fh.seek(file_size - offset)
            buffer = fh.read(min(remaining_size, buf_size))
            remaining_size -= buf_size
            lines = buffer.split('\n')
            # The first line of the buffer is probably not a complete line so
            # we'll save it and append it to the last line of the next buffer
            # we read
            if segment is not None:
                # If the previous chunk starts right from the beginning of line
                # do not concat the segment to the last line of new chunk.
                # Instead, yield the segment first
                if buffer[-1] != '\n':
                    lines[-1] += segment
                else:
                    yield segment
            segment = lines[0]
            for index in range(len(lines) - 1, 0, -1):
                if lines[index]:
                    yield lines[index]
        # Don't yield None if the file was empty
        if segment is not None:
            yield segment





def check_stream(url: str) -> bool:
    if ".m3u8" in url.lower():
        return is_streaming_site(url)
    return False


def is_streaming_site(url: str) -> bool:
    for p in STREAMING_PATTERNS:
        if p in url.lower():
            return True
    return False


def is_http(f: str) -> bool:
    if len(f.split("http-")) == 2:
        try:
            int(f.split("http-")[1])
        except ValueError:
            try:
                int(f.split("-")[1])
            except ValueError:
                return False
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


def valid_video_url(url: str) -> bool:
    if not url or not isinstance(url, str):
        return False

    u = urlparse(url)

    if u.scheme not in ["http", "https", "ftp"]:
        return False
    elif u.netloc.startswith("127.") or u.netloc.startswith("localhost"):
        return False
    elif u.netloc.startswith("192.") or u.netloc.startswith("10.0."):
        return False

    return True


def fix_youtube_shorts(url: str) -> str:
    if "youtube.com/shorts/" in url:
        return url.replace("/shorts/", "/embed/")
    return url


def fix_reddit_old(url: str) -> str:
    if "old.reddit.com" in url:
        return url.replace("old.", "")
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


