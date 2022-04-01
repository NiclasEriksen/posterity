import os
import ffmpeg
from tempfile import NamedTemporaryFile
from PIL import Image, ImageFilter, ImageOps, UnidentifiedImageError
from dotenv import load_dotenv

load_dotenv()


def generate_video_images(
    video_path: str, thumbnail_path: str, preview_path: str,
    blurred_thumb_path: str, blurred_preview_path: str,
    preview_size: tuple = (1280, 720), thumbnail_size: tuple = (64, 64),
    blur_amount: float = 0.33, desaturate: bool = False, start: float = 0.0
):

    raw_frame = NamedTemporaryFile(suffix=".png")

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
        preview_blurred = ImageOps.grayscale(preview_blurred)
        thumb_blurred = ImageOps.grayscale(thumb_blurred)

    preview = img.convert("P", palette=Image.ADAPTIVE, colors=256)
    preview_blurred = preview_blurred.convert("P", palette=Image.ADAPTIVE, colors=256)
    thumb = thumb.convert("P", palette=Image.ADAPTIVE, colors=64)
    thumb_blurred = thumb_blurred.convert("P", palette=Image.ADAPTIVE, colors=64)

    try:
        preview.save(preview_path, optimize=True)
        preview_blurred.save(blurred_preview_path, optimize=True)
        thumb.save(thumbnail_path, optimize=True)
        thumb_blurred.save(blurred_thumb_path, optimize=True)
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
        generate_video_images(
            video_path,
            os.path.join(thumbnail_path, video_id + "_thumb.png"),
            os.path.join(preview_path, video_id + "_preview.png"),
            os.path.join(thumbnail_path, video_id + "_thumb_blurred.png"),
            os.path.join(preview_path, video_id + "_preview_blurred.png"),
            start=5 if info["duration"] > 10.0 else 0,
            blur_amount=0.75,
            desaturate=True
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
