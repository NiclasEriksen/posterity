import os
import ffmpeg
import json
from tempfile import NamedTemporaryFile
from PIL import Image, ImageFilter, ImageOps, UnidentifiedImageError, \
    ImageDraw, ImageFont
from dotenv import load_dotenv

try:
    from PIL.Image import Palette
    palette = Palette.ADAPTIVE
except ImportError:
    palette = Image.ADAPTIVE


load_dotenv()
TEXT_MARGIN = 12
TEXT_PADDING = 8
STROKE_SMALL = 1
STROKE_MEDIUM = 2
STROKE_LARGE = 3
FONT_SIZE_SMALL = 24
FONT_SIZE_MEDIUM = 32
FONT_SIZE_LARGE = 42
FONT_COLOR = (192, 192, 192)
GRAPHIC_COLOR = (225, 96, 112)
EMOTIONAL_COLOR = (239, 198, 99)
FONT_GS = 128
GRAPHIC_GS = 0
EMOTIONAL_GS = 64
FONT_STROKE_COLOR = (32, 32, 32)
GRAPHIC_STROKE_COLOR = (32, 32, 32)
EMOTIONAL_STROKE_COLOR = (32, 32, 32)
FONT_STROKE_GS = 255
GRAPHIC_STROKE_GS = 255
EMOTIONAL_STROKE_GS = 192

"""
    --primary: #2C97DE;
    --primary-light: #6caed9;
    --primary-dark: #1c5e8a;
    --info: var(--primary);
    --success: #2DBDA8;
    --warning-light: #EFC663;
    --warning: #D9A322;
    --danger: #E16070;
    --bg: #232830;
    --grey: #EEE;
    --light-grey: #C2C8CF;
    --dark-grey: #2E353D;
    --charcoal: #353C45;
    --white: #FFF;
    --black: #13181f;
    --tag-informative: #00819e;
    --tag-informative: var(--primary);
    --tag-emotional: #e6ac00;
    --tag-emotional: var(--warning);
    --tag-graphic: #cf2900;
    --tag-graphic: var(--danger);
    --category: var(--light-grey);
"""


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
    video_path: str, thumbnail_path: str, preview_path: str,
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
        print(e)
        return

    try:
        img = Image.open(raw_frame.name)
    except (PermissionError, FileNotFoundError, UnidentifiedImageError) as e:
        print(e)
        return

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
        preview.save(preview_path, optimize=True, quality=75)
        preview_blurred.save(blurred_preview_path, optimize=True, quality=75)
        thumb.save(thumbnail_path, optimize=True, quality=60)
        thumb_blurred.save(blurred_thumb_path, optimize=True, quality=60)
    except (PermissionError, IOError, FileExistsError) as e:
        print(e)


def technical_info(video_path: str) -> dict:
    info = {
        "file_size": 0,
        "duration": 0.0,
        "dimensions": (0, 0),
        "bit_rate": 0,
        "fps": 0,
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
                            info["fps"] = int(int(total) / int(divisor))
                        else:
                            info["fps"] = int(fps)
                    except (ValueError, TypeError, AttributeError):
                        pass

            elif stream["codec_type"] == "audio":
                if "codec_name" in stream:
                    info["audio_codec"] = stream["codec_name"]
                elif "codec_tag_string" in stream:
                    info["audio_codec"] = stream["codec_tag_string"]
                elif "codec_long_name" in stream:
                    info["audio_codec"] = stream["codec_long_name"]
                info["audio"] = True
            elif stream["codec_type"] == "subtitle":
                pass

    return info


def generate_all_images(
    media_path: str, thumbnail_path: str, preview_path: str, only_new=True
):
    videos = []
    for file_name in os.listdir(media_path):
        if file_name.endswith(".mp4"):
            videos.append((file_name.split(".mp4")[0], os.path.join(media_path, file_name)))

    for (video_id, video_path) in videos:
        info = technical_info(video_path)

        json_path = os.path.join(media_path, video_id + ".json")
        try:
            with open(json_path) as f:
                d = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            continue

        if "content_warning" in d.keys():
            content_text = d["content_warning"] if d["content_warning"].lower().strip() != "none" else ""
        else:
            content_text = ""

        generate_video_images(
            video_path,
            os.path.join(thumbnail_path, video_id + "_thumb.jpg"),
            os.path.join(preview_path, video_id + "_preview.jpg"),
            os.path.join(thumbnail_path, video_id + "_thumb_blurred.jpg"),
            os.path.join(preview_path, video_id + "_preview_blurred.jpg"),
            start=5 if info["duration"] > 30.0 else 0,
            blur_amount=0.75,
            desaturate=False,
            content_text=content_text
        )


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
    media_path = os.environ.get("MEDIA_FOLDER", "")
    thumbnail_path = os.environ.get("THUMBNAIL_FOLDER", "")
    preview_path = os.environ.get("PREVIEW_FOLDER", "")
    if len(media_path) and len(thumbnail_path) and len(preview_path):
        generate_all_images(
            media_path,
            thumbnail_path,
            preview_path,
            only_new=False
        )
