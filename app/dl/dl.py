import logging
import json
import os
import subprocess
import ffmpeg
from app import celery
from tempfile import NamedTemporaryFile
from PIL import Image, ImageFilter, ImageOps, UnidentifiedImageError, \
    ImageDraw, ImageFont
try:
    from PIL.Image import Palette
    palette = Palette.ADAPTIVE
except ImportError:
    palette = Image.ADAPTIVE

from .youtube import get_content_info, AgeRestrictedError
from .helpers import valid_video_url
from .metadata import technical_info, add_technical_info_to_metadata, find_best_format, \
    check_duplicate_for_video, get_frame_count_from_log
from . import FONT_SIZE_SMALL, FONT_SIZE_MEDIUM, FONT_SIZE_LARGE, CRF, CRF_LOW, \
    preview_path, thumbnail_path, tmp_path, original_path, \
    STATUS_DOWNLOADING, STATUS_COMPLETED, STATUS_FAILED, STATUS_INVALID, STATUS_COOKIES, STATUS_PROCESSING, \
    MAX_DURATION_HD, MAX_DURATION_MD, MAX_AUD_BIT_RATE, MAX_RESOLUTION_MD, MAX_RESOLUTION_SD, MAX_DURATION_SD, \
    MAX_FPS, SPLIT_FPS_THRESHOLD, MAX_BIT_RATE_PER_PIXEL, MIN_BIT_RATE_PER_PIXEL, \
    GRAPHIC_COLOR, GRAPHIC_GS, GRAPHIC_STROKE_COLOR, GRAPHIC_STROKE_GS, \
    EMOTIONAL_COLOR, EMOTIONAL_GS, EMOTIONAL_STROKE_COLOR, EMOTIONAL_STROKE_GS, \
    FONT_COLOR, FONT_GS, FONT_STROKE_COLOR, FONT_STROKE_GS, \
    STROKE_SMALL, STROKE_MEDIUM, STROKE_LARGE, TEXT_PADDING, TEXT_MARGIN, STATUS_CHECKING

# log = LocalProxy(lambda: current_app.logger)
log = logging.getLogger("posterity_dl.dl")

if celery:
    inspector = celery.control.inspect()

overlay_font_small = ImageFont.truetype(
    os.path.join(
        os.path.dirname(os.path.realpath(__file__)),
        "Faustina-SemiBold.ttf"
    ), FONT_SIZE_SMALL
)
overlay_font_medium = ImageFont.truetype(
    os.path.join(
        os.path.dirname(os.path.realpath(__file__)),
        "Faustina-SemiBold.ttf"
    ), FONT_SIZE_MEDIUM
)
overlay_font_large = ImageFont.truetype(
    os.path.join(
        os.path.dirname(os.path.realpath(__file__)),
        "Faustina-SemiBold.ttf"
    ), FONT_SIZE_LARGE
)


def process_from_json_data(metadata: dict, input_file: str, output_file: str) -> dict:
    metadata["status"] = STATUS_PROCESSING
    yield metadata

    info = technical_info(input_file)

    vid_bit_rate = info["vid_bit_rate"]
    aud_bit_rate = info["vid_bit_rate"]
    fps = info["fps"]

    if fps >= SPLIT_FPS_THRESHOLD and fps <= MAX_FPS:
        fps *= 0.5
    elif fps > MAX_FPS:
        fps = MAX_FPS

    try:
        pixels = (info["dimensions"][0] * info["dimensions"][1])
    except (KeyError, IndexError):
        pixels = 921600 * (fps / 30.0)     # 720p

    max_bit_rate = pixels * MAX_BIT_RATE_PER_PIXEL
    min_bit_rate = pixels * MIN_BIT_RATE_PER_PIXEL
    r = max_bit_rate - min_bit_rate
    br = min(1.0, max(0.0, vid_bit_rate - min_bit_rate) / r)

    crf = int(CRF + (CRF_LOW - CRF) * br)

    vid_bit_rate = min(vid_bit_rate, max_bit_rate) // 1000
    aud_bit_rate = min(aud_bit_rate // 1000, MAX_AUD_BIT_RATE)

    log_path = os.path.join(tmp_path, metadata['video_id'] + "_progress.log")
    try:
        open(log_path, "w").close()
    except:
        log_path = "/dev/null"

    cmd = get_post_process_ffmpeg_cmd(
        input_file, output_file,
        fps=fps, vid_bit_rate=vid_bit_rate,
        aud_bit_rate=aud_bit_rate, crf=crf,
        log_path=log_path
    )

    # metadata["processed_bit_rate"] = (vid_bit_rate + aud_bit_rate) * 1000
    # metadata["processed_frame_rate"] = (vid_bit_rate + aud_bit_rate) * 1000

    if "&&" in cmd:
        pass_1 = cmd[:cmd.index("&&")]
        pass_2 = cmd[cmd.index("&&")+1:]
    else:
        pass_1 = cmd
        pass_2 = []

    for i, p in enumerate([pass_1, pass_2]):
        if not len(p):
            continue

        log.info(f"{metadata['video_id']} | Running pass {i}...")

        result = subprocess.Popen(p, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

        metadata["pid"] = result.pid
        yield metadata
        output, errors = result.communicate()

        if result.returncode != 0:
            try:
                open(log_path, "w").close()
            except:
                pass
            log.error(output)
            log.error(errors)
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
        try:
            open(log_path, "w").close()
        except:
            pass

    #os.chdir(cur_dir)

    yield metadata


def download_from_json_data(metadata: dict, file_name: str):
    from app.serve.db import Video
    vid_save_path = os.path.join(original_path, file_name + ".mp4")

    if not valid_video_url(metadata["url"]):
        log.error("Invalid video url...")
        metadata["status"] = STATUS_INVALID
        yield metadata

    elif original_path == "":
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
    except Exception as e:
        log.error(e)
        log.error("Unhandled exception during fetching of content info.")
        metadata["status"] = STATUS_FAILED
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
    uploaded = d["upload_date"]

    if duration > MAX_DURATION_SD:
        log.error("Video is too long to download! Duration: " + str(duration))
        metadata["status"] = STATUS_INVALID
        yield metadata

    limit = 2160
    if duration > MAX_DURATION_MD:
        limit = MAX_RESOLUTION_SD
    elif duration > MAX_DURATION_HD:
        limit = MAX_RESOLUTION_MD

    f, audio_included = find_best_format(
        d["video_formats"], limit=limit
    )

    print(f)
    audio_included = True

    video_url = video_links[f]["url"]

    if len(audio_formats) and not audio_included:
        audio_url = audio_links[audio_formats[-1]]
    else:
        audio_url = ""
    if len(sub_formats):
        sub_url = sub_links[sub_formats[-1]]
    else:
        sub_url = ""

    log_path = os.path.join(tmp_path, metadata['video_id'] + "_progress.log")
    try:
        open(log_path, "w").close()
    except:
        log_path = "/dev/null"

    print("===================")
    print(f"Format: {f}, audio: {audio_included}")
    if not audio_included:
        print(f"Audio in video stream")
    print("===================")

    cmd = get_ffmpeg_cmd(video_url, audio_url, sub_url, vid_save_path, log_path=log_path)

    metadata["video_title"] = video_title
    metadata["format"] = f
    metadata["duration"] = duration
    metadata["status"] = STATUS_DOWNLOADING
    metadata["orig_upload_time"] = uploaded

    yield metadata

    result = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    metadata["pid"] = result.pid
    yield metadata
    output, errors = result.communicate()
    # result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    if result.returncode != 0:
        log.error(output)
        log.error(errors)
        log.error("Well this all went to shit. Removing video.")

        try:
            os.remove(vid_save_path)
        except (FileNotFoundError, OSError):
            pass
        try:
            open(log_path, "w").close()
        except:
            pass

        metadata["status"] = STATUS_FAILED
        metadata["task_id"] = ""
        metadata["pid"] = -1
        yield metadata

    else:
        metadata = add_technical_info_to_metadata(metadata, vid_save_path)
        metadata["status"] = STATUS_CHECKING
        yield metadata

        metadata["pid"] = -1
        metadata["task_id"] = ""
        metadata["status"] = STATUS_COMPLETED

        try:
            open(log_path, "w").close()
        except:
            pass

        valid = validate_video_file(vid_save_path, log_path, metadata["frame_rate"], metadata["duration"])

        try:
            open(log_path, "w").close()
        except:
            pass

        if not valid:
            metadata["status"] = STATUS_FAILED

        elif len(thumbnail_path) and len(preview_path):
            try:
                log.info("Generating images")

                success = generate_video_images(
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
                success = False
                log.error(e)
                log.error("FAILED THUMBNAIL GENERATION")
            else:
                if success:
                    log.info("Checking for duplicates")
                    duplicates = check_duplicate_for_video(file_name)
                    if duplicates:
                        log.error(f"Found {duplicates} possible duplicates.")

            if not success:
                metadata["status"] = STATUS_FAILED

    yield metadata


def validate_video_file(
        video_path: str, log_path: str, fps: int, duration: float,
) -> True:
    result = subprocess.Popen(
        ["ffmpeg", "-v", "24", "-i", video_path, "-progress", log_path, "-f", "null", "/dev/null"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )
    _output, _errors = result.communicate()
    if result.returncode != 0:
        log.error(_output)
        log.error(_errors)
        log.error("Unable to verify video file.")
        return False
    else:
        log.info("Checking log file for frame count.")
        frames = get_frame_count_from_log(log_path)
        if not frames > 0:
            log.error("No frames!")
            return False
        if (fps * duration * 0.9) < frames < (fps * duration * 1.1):
            return True

        return False


def get_post_process_ffmpeg_cmd(
        input_path: str, output_path: str, queue_size=512,
        fps=25, vid_bit_rate=2000, aud_bit_rate=128, crf=CRF, log_path="/dev/null"
    ) -> list:

    pass_1 = [
        "ffmpeg", "-thread_queue_size", f"{queue_size}", "-y",
        "-vsync", "vfr",
        "-i", input_path,
        "-c:v", "libx264", "-filter:v", f"yadif=parity=auto[v];[v]fps={fps}", "-pix_fmt", "yuv420p", "-vprofile", "main", "-vlevel", "4", "-preset", "veryslow",
        "-b:v", f"{vid_bit_rate}k", "-crf", str(crf),
        "-c:a", "aac", "-strict", "experimental", "-b:a", f"{aud_bit_rate}k",
        "-progress", log_path, "-v", "34", output_path
    ]

    return pass_1


def get_ffmpeg_cmd(
    vid_url, aud_url, _sub_url, save_path, normalize=True,
    http_persistent=True, queue_size=512, crf=24, log_path="/dev/null"
) -> list:

    cmd = [
        "ffmpeg", "-thread_queue_size", f"{queue_size}", "-y",
        "-i", vid_url
    ]

    if len(aud_url) and not (vid_url == aud_url):
        cmd += ["-thread_queue_size", f"{queue_size}"]
        cmd += ["-i", aud_url]
        cmd += ["-map", "0:v", "-map", "1:a"]
    elif (vid_url == aud_url):
        print("Trying to use same audio source as video.")

    cmd += ["-acodec", "aac"]
    # Apply sound normalization
    if normalize:
        # dynamic norm
        cmd += ["-af", "dynaudnorm=p=0.85"]

    cmd += ["-vcodec", "libx264", "-crf", str(crf), "-f", "mp4"]

    if http_persistent:
        cmd += ["-http_persistent", "1"]
    else:
        cmd += ["-http_persistent", "0"]

    cmd += ["-progress", log_path, "-v", "34", save_path]

    return cmd


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


def get_color_for_tag(tag: str, gs: bool = False) -> tuple:
    if tag.lower() in [
        "death", "graphic", "violence", "gore", "nudity", "corpses", "blood"
    ]:
        c = tuple([GRAPHIC_GS]) if gs else GRAPHIC_COLOR
    elif tag.lower() in [
        "distress", "animals", "children", "sexual", "shock", "emotional"
    ]:
        c = tuple([EMOTIONAL_GS]) if gs else EMOTIONAL_COLOR
    else:
        c = tuple([FONT_GS]) if gs else FONT_COLOR
    return c


def get_stroke_for_tag(tag: str, gs: bool = False) -> tuple:
    if tag.lower() in [
        "death", "graphic", "violence", "gore", "nudity", "corpses", "blood"
    ]:
        c = tuple([GRAPHIC_STROKE_GS]) if gs else GRAPHIC_STROKE_COLOR
    elif tag.lower() in [
        "distress", "animals", "children", "sexual", "shock", "emotional"
    ]:
        c = tuple([EMOTIONAL_STROKE_GS]) if gs else EMOTIONAL_STROKE_COLOR
    else:
        c = tuple([FONT_STROKE_GS]) if gs else FONT_STROKE_COLOR
    return c


def generate_video_images(
    video_path: str, thumb_out_path: str, preview_out_path: str,
    blurred_thumb_path: str, blurred_preview_path: str,
    preview_size: tuple = (640, 360), thumbnail_size: tuple = (64, 64),
    blur_amount: float = 0.66, desaturate: bool = False, start: float = 0.0,
    content_text: str = ""
):

    raw_frame = NamedTemporaryFile(suffix=".jpg")

    try:
        _d = (
            ffmpeg
            .input(video_path, ss=start)
            .filter('scale', preview_size[0], -1)
            .output(raw_frame.name, vframes=1)
            .overwrite_output()
            .run(quiet=True)
        )
    except ffmpeg.Error as e:
        log.error(e)
        return False

    try:
        img = Image.open(raw_frame.name)
    except (PermissionError, FileNotFoundError, UnidentifiedImageError) as e:
        log.error(e)
        return False

    thumb = img.copy()

    img.thumbnail(preview_size)
    thumb.thumbnail(thumbnail_size)
    preview_blurred = img.copy()
    thumb_blurred = thumb.copy()

    preview_blurred = preview_blurred.filter(
        ImageFilter.GaussianBlur(preview_size[0] / 32 * blur_amount)
    )
    thumb_blurred = thumb_blurred.filter(
        ImageFilter.GaussianBlur(thumbnail_size[0] / 16 * blur_amount)
    )

    if desaturate:
        preview_blurred_desat = ImageOps.grayscale(preview_blurred)
        preview_blurred.paste(preview_blurred_desat)
        thumb_blurred = ImageOps.grayscale(thumb_blurred)

    if len(content_text):
        preview_draw = ImageDraw.Draw(img)
        preview_blurred_draw = ImageDraw.Draw(preview_blurred)

        ratio = min([
            min(1.0, max(0.0, img.size[0] / preview_size[0])),
            min(1.0, max(0.0, img.size[1] / preview_size[1]))
        ])
        padding = int(TEXT_PADDING * ratio)
        if ratio > 0.75:
            size = FONT_SIZE_LARGE
            stroke = STROKE_LARGE
            font = overlay_font_large
        elif ratio > 0.5:
            size = FONT_SIZE_MEDIUM
            stroke = STROKE_MEDIUM
            font = overlay_font_medium
        else:
            size = FONT_SIZE_SMALL
            stroke = STROKE_SMALL
            font = overlay_font_small

        if "/" in content_text:
            lines = content_text.split("/")
        else:
            lines = [content_text]

        lines = [l for l in lines if l.strip().lower() != "none"]

        for i, line in enumerate(lines):
            preview_draw.text(
                (TEXT_MARGIN, i * (size + padding) + TEXT_MARGIN),
                line, font=font,
                fill=get_color_for_tag(line), stroke_width=stroke, stroke_fill=get_stroke_for_tag(line)
            )
            preview_blurred_draw.text(
                (TEXT_MARGIN, i * (size + padding) + TEXT_MARGIN),
                line, font=font,
                fill=get_color_for_tag(line), stroke_width=stroke, stroke_fill=get_stroke_for_tag(line)
            )

    preview = img
    # preview = img.convert("P", palette=palette, colors=256)
    # preview_blurred = preview_blurred.convert("P", palette=palette, colors=256)
    # thumb = thumb.convert("P", palette=palette, colors=64)
    # thumb_blurred = thumb_blurred.convert("P", palette=palette, colors=64)

    try:
        preview.save(preview_out_path, optimize=True, quality=75)
        preview_blurred.save(blurred_preview_path, optimize=True, quality=75)
        thumb.save(thumb_out_path, optimize=True, quality=60)
        thumb_blurred.save(blurred_thumb_path, optimize=True, quality=60)
    except (PermissionError, IOError, FileExistsError) as e:
        log.error(e)
        return False

    return True


def generate_logo(
        orig_path: str, width=96, height=32
):
    try:
        img = Image.open(orig_path)
    except (PermissionError, FileNotFoundError, UnidentifiedImageError) as e:
        print(e)
        return

    img.thumbnail((width, height))
    img.save(orig_path)


def generate_all_images(
    orig_path: str, json_path: str, thumbnail_path: str, preview_path: str, only_new=True
):
    videos = []
    for file_name in os.listdir(orig_path):
        if file_name.endswith(".mp4"):
            videos.append((file_name.split(".mp4")[0], os.path.join(orig_path, file_name)))

    for (video_id, video_path) in videos:
        info = technical_info(video_path)

        jp = os.path.join(json_path, video_id + ".json")
        try:
            with open(jp) as f:
                d = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            continue

        if "content_warning" in d.keys():
            content_text = d["content_warning"] if d["content_warning"].lower().strip() != "none" else ""
        else:
            content_text = ""

        success = generate_video_images(
            video_path,
            os.path.join(thumbnail_path, video_id + "_thumb.jpg"),
            os.path.join(preview_path, video_id + "_preview.jpg"),
            os.path.join(thumbnail_path, video_id + "_thumb_blurred.jpg"),
            os.path.join(preview_path, video_id + "_preview_blurred.jpg"),
            start=5 if info["duration"] > 10.0 else 0,
            blur_amount=0.75,
            desaturate=False,
            content_text=content_text
        )
        if not success:
            log.error(f"Failed generating images for {video_id}")



if __name__ == "__main__":
    # download_video(
    #     "https://rr9---sn-uxaxovg-vnaee.googlevideo.com/videoplayback?expire=1645245333&ei=NR8QYr-MENTJyQX_t4OACw&ip=2a02%3A2121%3A348%3A4446%3A10%3A2030%3A4050%3A2&id=o-ALeH5AJ4EFS3jd7JmT4n3wqUJVDGzdzd1VoGQ9a7GG88&itag=134&aitags=133%2C134%2C135%2C136%2C137%2C160%2C242%2C243%2C244%2C247%2C248%2C278%2C394%2C395%2C396%2C397%2C398%2C399&source=youtube&requiressl=yes&mh=D9&mm=31%2C29&mn=sn-uxaxovg-vnaee%2Csn-5go7ynld&ms=au%2Crdu&mv=m&mvi=9&pl=45&initcwndbps=1733750&vprv=1&mime=video%2Fmp4&ns=j-jWRtzzhaM_EIbeSt022XEG&gir=yes&clen=10563747&dur=671.237&lmt=1645152417253074&mt=1645223348&fvip=3&keepalive=yes&fexp=24001373%2C24007246&c=WEB&txp=5535434&n=NitbMne41cfvwE91N&sparams=expire%2Cei%2Cip%2Cid%2Caitags%2Csource%2Crequiressl%2Cvprv%2Cmime%2Cns%2Cgir%2Cclen%2Cdur%2Clmt&sig=AOq0QJ8wRQIhAO4EQxTPvCXqWuRzQBWtWGy7yWJ7EeoNdrnJgd08ZvP7AiB363rWmaI8Q0PEz9PZ1GMXNN_okwgufV-t-P_rnKx-yA%3D%3D&lsparams=mh%2Cmm%2Cmn%2Cms%2Cmv%2Cmvi%2Cpl%2Cinitcwndbps&lsig=AG3C_xAwRQIhAMCjcsawNwRFPFRFr6cFnPp_SI7q526biJlrD9nn5SgBAiBYkGGtUTDFDwB75aWNxekWphIUXbf4wQpmzQi6QJAaPg%3D%3D",
    #     "https://rr9---sn-uxaxovg-vnaee.googlevideo.com/videoplayback?expire=1645245382&ei=Zh8QYuTaGsnvyQW1oKzwCw&ip=2a02%3A2121%3A348%3A4446%3A10%3A2030%3A4050%3A2&id=o-AH-GmHLDmdxfUifh6MiZQ0BAAisYVpYCYUhx_gQpCg5r&itag=250&source=youtube&requiressl=yes&mh=D9&mm=31%2C29&mn=sn-uxaxovg-vnaee%2Csn-5go7ynld&ms=au%2Crdu&mv=m&mvi=9&pcm2cms=yes&pl=45&initcwndbps=1803750&vprv=1&mime=audio%2Fwebm&ns=5Utx-DOvqnMih9M12BtNJYMG&gir=yes&clen=6065299&dur=671.261&lmt=1645149148063252&mt=1645223578&fvip=3&keepalive=yes&fexp=24001373%2C24007246&c=WEB&txp=5532434&n=YuW1MUOjMKnvXIHZC&sparams=expire%2Cei%2Cip%2Cid%2Citag%2Csource%2Crequiressl%2Cvprv%2Cmime%2Cns%2Cgir%2Cclen%2Cdur%2Clmt&sig=AOq0QJ8wRQIhAKQksmG6Fo5SkUSI-XnxKHGexRKC7MnSJ3P3qKlrnuUXAiAHKJdD0u5yi4CRGGICYyJ7Ap-EoLyXormsDZTCO_3VrA%3D%3D&lsparams=mh%2Cmm%2Cmn%2Cms%2Cmv%2Cmvi%2Cpcm2cms%2Cpl%2Cinitcwndbps&lsig=AG3C_xAwRAIgW07Ly1M8T5mIQ1EadfTzHkbpDWs6unS_mWr5oAhjj2sCIHjLLHF9vl0sy4S66AqEHcadIk8Gd_mITtSpctQxqRkR",
    #     "test.mp4", start=340, end=360
    # )
    pass
