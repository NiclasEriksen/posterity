import os
import sys
import math
from datetime import datetime
import shortuuid


def unique_filename() -> str:
    return datetime.now().strftime("%y%m%d-%H%M%S") + "-" + shortuuid.uuid()[:5]


def find_between( s, first, last ):
    try:
        start = s.index( first ) + len( first )
        end = s.index( last, start )
        return s[start:end]
    except ValueError:
        return ""


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