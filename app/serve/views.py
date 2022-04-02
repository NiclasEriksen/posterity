import os
import functools
from dotenv import load_dotenv
import json
from datetime import datetime
from flask import Blueprint, current_app, request, abort,\
    render_template, send_from_directory, url_for, flash,\
    redirect, get_flashed_messages
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import login_user, login_required, logout_user, current_user
from redis.exceptions import ConnectionError
from sqlalchemy.exc import OperationalError, IntegrityError
from werkzeug.local import LocalProxy

serve = Blueprint(
    'serve', __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/serve-static"
)
logger = LocalProxy(lambda: current_app.logger)

from app.dl.dl import media_path, \
    STATUS_COMPLETED, STATUS_COOKIES, STATUS_DOWNLOADING, STATUS_FAILED, STATUS_INVALID, \
    get_celery_scheduled, get_celery_active, write_metadata
from app.serve.db import db_session, Video, User, ContentTag, Category,\
    init_db, AUTH_LEVEL_ADMIN, AUTH_LEVEL_MOD, AUTH_LEVEL_USER
from app import get_environment, app_config
from app.serve.search import search_videos, index_video_data, remove_video_data, remove_video_data_by_id
from app.extensions import cache


# Setup
init_db()
load_dotenv()
APPLICATION_ENV = get_environment()
MAX_RESULT_PER_PAGE = 30
TORRENT_NAME = "Posterity.Ukraine.archive.torrent"


def catch_redis_errors(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except ConnectionError as e:
            logger.debug(e)
            logger.error("Error during handling of Redis request, ignoring.")
    return wrapper


@serve.teardown_request
def remove_session(*_args):
    db_session.remove()


@serve.before_request
def before_request_func():
    current_app.logger.name = "posterity.serve"


@serve.route("/", methods=["GET"])
def front_page():
    page = request.args.get("p", type=int, default=1)
    pp = request.args.get("pp", type=int, default=MAX_RESULT_PER_PAGE)
    kw = request.args.get("q", type=str, default="")

    offset = max(0, page - 1) * pp

    if len(kw):
        logger.info(f"Searching for {kw}.")
        results = search_videos(kw)
        results = sorted(results, key=lambda x: x["_score"], reverse=True)
        # logger.info(results)

        videos = []
        total = len(results)
        for result in results[offset:offset + MAX_RESULT_PER_PAGE]:
            v = Video.query.filter_by(video_id=result["_id"]).first()
            if v:
                videos.append(v)
            else:
                remove_video_data_by_id(result["_id"])

    else:
        vq = Video.query
        total = vq.count()

        videos = vq.order_by(Video.upload_time.desc()).offset(offset).limit(pp).all()

    total_pages = total // pp + (1 if total % pp else 0)

    available_tags = ContentTag.query.order_by(ContentTag.name).all()
    available_categories = Category.query.order_by(Category.name).all()

    return render_template(
        "home.html", videos=videos,
        current_page=page,
        result_offset=offset,
        max_page=total_pages,
        per_page=pp,
        total=total,
        total_results=len(videos),
        keyword=kw,
        tags=available_tags,
        categories=available_categories
    )


@serve.route("/", methods=["POST"])
def front_page_search():
    page = request.args.get("p", type=int, default=1)
    # pp = request.args.get("pp", type=int, default=MAX_RESULT_PER_PAGE)
    kw = request.form.get("keyword", default="")

    return redirect(url_for("serve.front_page", p=page, q=kw))


@serve.route("/<video_id>", methods=["GET"])
def serve_video(video_id):
    logger.info(f"Requested video '{video_id}'.")

    metadata = get_metadata_for_video(video_id)

    dl_video_id = video_id

    if "duplicate" in metadata.keys():
        if len(metadata["duplicate"]):
            new_video_id = metadata["duplicate"]
            new_metadata = get_metadata_for_video(new_video_id)
            new_metadata["title"] = metadata["title"]
            new_metadata["content_warning"] = metadata["content_warning"]
            dl_video_id = new_metadata["video_id"]
            metadata = new_metadata
            metadata["video_id"] = video_id

    if not len(metadata.keys()):
        logger.error("Invalid metadata from json file.")
        return render_template("not_found.html")

    video = Video.query.filter_by(video_id=video_id).first()
    if video:
        tags = video.tags
        categories = video.categories
    else:
        tags = []
        categories = []

    if metadata["status"] in [STATUS_FAILED, STATUS_INVALID]:
        flash("Video failed to download, this page will self destruct")
        logger.warning("Doing 'burn-after-read' on video")
        _success = delete_video_by_id(video_id)

    return render_template(
        "video.html",
        custom_title=metadata["title"],
        orig_title=metadata["video_title"],
        status=metadata["status"] if "status" in metadata else 2,
        duration=int(metadata["duration"]),
        video=video,
        source=metadata["source"],
        content_warning=metadata["content_warning"],
        tags=tags,
        categories=categories,
        dl_path="/download/" + dl_video_id,
        stream_path="/view/" + dl_video_id,
        orig_url=metadata["url"],
        video_format=metadata["format"],
        upload_time=metadata["upload_time"],
        video_id=video_id
    )


@serve.route("/edit_video/<video_id>", methods=["GET"])
@login_required
def edit_video_page(video_id: str):
    video: Video = Video.query.filter_by(video_id=video_id).first()
    if not video:
        return render_template("not_found.html")

    available_tags = ContentTag.query.order_by(ContentTag.name).all()
    available_categories = Category.query.order_by(Category.name).all()

    for at in available_tags:
        if at in video.tags:
            at.enabled = True
        else:
            at.enabled = False
    for ac in available_categories:
        if ac in video.categories:
            ac.enabled = True
        else:
            ac.enabled = False

    return render_template(
        "edit_video.html",
        custom_title=video.title,
        verified=video.verified,
        source=video.source,
        tags=available_tags,
        categories=available_categories,
        video_id=video_id
    )


@serve.route("/edit_video/<video_id>", methods=["POST"])
@login_required
def edit_video_post(video_id: str):
    video: Video = Video.query.filter_by(video_id=video_id).first()
    if not video:
        return render_template("not_found.html")

    title = request.form.get("custom_title")
    verified = True if request.form.get("verified") == "verified_on" else False
    source = request.form.get("source")
    tl = request.form.getlist("tags_select")
    cl = request.form.getlist("categories_select")

    video.tags = []
    for tag_id in tl:
        try:
            tag_id = int(tag_id)
        except (TypeError, ValueError):
            logger.error("Invalid tag value in form?")
            continue
        else:
            tag = ContentTag.query.filter_by(id=tag_id).first()
            if tag and tag not in video.tags:
                video.tags.append(tag)

    video.categories = []
    for category_id in cl:
        try:
            category_id = int(category_id)
        except (TypeError, ValueError):
            logger.error("Invalid category value in form?")
            continue
        else:
            cat = Category.query.filter_by(id=category_id).first()
            if cat and cat not in video.categories:
                video.categories.append(cat)

    video.title = title
    video.verified = verified
    video.source = source

    db_session.add(video)
    db_session.commit()
    write_metadata(video_id, video.to_json())

    available_tags = ContentTag.query.order_by(ContentTag.name).all()
    available_categories = Category.query.order_by(Category.name).all()

    for at in available_tags:
        if at in video.tags:
            at.enabled = True
        else:
            at.enabled = False
    for ac in available_categories:
        if ac in video.categories:
            ac.enabled = True
        else:
            ac.enabled = False

    flash(f"Video info for \"{video_id}\"has been updated.", "success")

    return render_template(
        "edit_video.html",
        custom_title=video.title,
        verified=video.verified,
        source=video.source,
        tags=available_tags,
        categories=available_categories,
        video_id=video_id
    )


@serve.route("/register", methods=["GET"])
def register_user_page():
    if current_user.is_authenticated:
        flash(f"You already have an account. Log out in order to register a new one.")
        return redirect(url_for("serve.front_page"))
    return render_template("register.html")


@serve.route("/register", methods=["POST"])
def register_user_post():
    username = request.form.get("username")
    password = request.form.get("password")
    token = request.form.get("token")

    if token != app_config[APPLICATION_ENV].REGISTER_TOKEN:
        flash(f"Invalid token for user registration.", "error")
        logger.error(f"Invalid token for user registration.")
        return redirect(url_for("serve.register_user_page"))

    if not len(password) >= 6:
        flash("Password needs to be 6 characters or longer.", "error")
        return redirect(url_for("serve.register_user_page"))
    
    if not len(username) >= 3:
        flash("Username needs to be 3 characters or longer.", "error")
        return redirect(url_for("serve.register_user_page"))

    existing_user = User.query.filter_by(username=username).first()
    if existing_user:
        flash("Username already taken, please choose another one.", "error")
        return redirect(url_for("serve.register_user_page"))

    password_hash = generate_password_hash(password)

    user = User()
    user.username = username
    user.password = password_hash
    user.auth_level = AUTH_LEVEL_MOD

    db_session.add(user)
    db_session.commit()

    login_user(user, remember=True)

    return redirect(url_for("serve.front_page"))


@serve.route("/logout")
@login_required
def logout_route():
    logout_user()
    flash("You have been logged out.", "success")
    return redirect(url_for("serve.front_page"))


@serve.route("/login", methods=["GET"])
def login_page():
    if current_user.is_authenticated:
        flash(f"You are already logged in.", "error")
        return redirect(url_for("serve.front_page"))
    get_flashed_messages()
    return render_template("login.html")


@serve.route("/login", methods=["POST"])
def login_post_route():
    username = request.form.get("username")
    password = request.form.get("password")

    user = User.query.filter_by(username=username).first()
    if not user:
        logger.error(f"Unable to log in with that user ({username}), it doesn't exist!")
        flash(f"Unable to log in with that user ({username}), it doesn't exist!", "error")
        return redirect(url_for("serve.login_page"))
    
    if not check_password_hash(user.password, password):
        logger.error(f"Unable to log in with user ({username}): passwords doesn't match.")
        flash(f"Unable to log in with that user ({username}), password is incorrect!", "error")
        return redirect(url_for("serve.login_page"))
    
    flash(f"You have been logged in!", "success")
    login_user(user, remember=True)
    return redirect(url_for("serve.front_page"))


@serve.route("/settings", methods=["GET", "POST"])
@login_required
def settings_page():
    tags = ContentTag.query.all()
    if not tags:
        tags = []

    if request.method == "POST":
        pass

    return render_template("settings.html", tags=tags)


@serve.route("/add_tag", methods=["POST"])
@login_required
def add_tag_post():
    tag_name = request.form.get("tag_name")
    tag_category = request.form.get("tag_category_select")
    try:
        tag_category = int(tag_category)
    except (ValueError, TypeError):
        tag_category = 0

    return_url = request.form.get("return_url")
    if tag_name:
        if tag_category > 1:
            tag_censor = True
        else:
            tag_censor = False

        existing = ContentTag.query.filter_by(name=tag_name.rstrip().lstrip()).first()

        if existing:
            flash("Tag by that name already exists, ignored.", "warning")
        else:
            tag = ContentTag(tag_name.rstrip().lstrip())
            tag.censor = tag_censor
            tag.category = tag_category
            db_session.add(tag)
            db_session.commit()
            flash("Tag added to database!", "success")
    else:
        flash("Tag name cannot be empty.", "error")

    return redirect(return_url, 302)


@serve.route("/add_category", methods=["POST"])
@login_required
def add_category_post():
    category_name = request.form.get("category_name")
    return_url = request.form.get("return_url")
    if category_name:

        existing = Category.query.filter_by(name=category_name.rstrip().lstrip()).first()

        if existing:
            flash("Category by that name already exists, ignored.", "warning")
        else:
            category = Category(category_name.rstrip().lstrip())
            db_session.add(category)
            db_session.commit()
            flash("Category added to database!", "success")
    else:
        flash("Category name cannot be empty.", "error")

    return redirect(return_url, 302)


@serve.route("/about", methods=["GET"])
def about_us_page():
    return render_template("about.html")


@serve.route("/remove/<video_id>")
@login_required
def remove_video_route(video_id):
    metadata = get_metadata_for_video(video_id)

    success = delete_video_by_id(video_id)
    if not success and not len(metadata.keys()):
        flash("No video by that id, nothing to remove.", "error")
    elif not success:
        flash("Error during removal of video, might be some residue.", "warning")
    else:
        flash(f"Video \"{video_id}\" has been deleted successfully!", "success")
    return redirect(url_for("serve.front_page"), code=302)


@serve.route("/download_archive", methods=["GET"])
def download_archive():
    torrent_path = os.path.join(media_path, TORRENT_NAME)
    try:
        mod_date = os.path.getmtime(torrent_path)
        last_updated = datetime.fromtimestamp(mod_date).strftime("%d.%m.%Y")
    except OSError:
        last_updated = "?"

    return render_template("download.html", last_updated=last_updated)


@serve.route("/download/<video_id>")
def download_video(video_id=""):
    try:
        if os.path.isfile(os.path.join(media_path, video_id + ".mp4")):
            return send_from_directory(media_path, video_id + ".mp4", as_attachment=True)
    except OSError as e:
        logger.error(e)
        logger.error("Unable to serve video!")
    return "Video file not found."


@serve.route("/view/<video_id>")
def view_video(video_id=""):
    try:
        if os.path.isfile(os.path.join(media_path, video_id + ".mp4")):
            return send_from_directory(media_path, video_id + ".mp4")
    except OSError as e:
        logger.error(e)
        logger.error("Unable to serve video!")
    return "Video file not found."


@serve.route("/preview/<video_id>.png")
@cache.memoize(timeout=360)
def get_preview_image_url(video_id=""):
    video = Video.query.filter_by(video_id=video_id).first()
    if video:
        if os.path.isfile(os.path.join(current_app.config["PREVIEW_FOLDER"], video_id + "_preview_blurred.png")):
            for ct in video.tags:
                if ct.category > 1:
                    return send_from_directory(current_app.config["PREVIEW_FOLDER"], video_id + "_preview_blurred.png")
        if os.path.isfile(os.path.join(current_app.config["PREVIEW_FOLDER"], video_id + "_preview.png")):
            return send_from_directory(current_app.config["PREVIEW_FOLDER"], video_id + "_preview.png")

    return serve.send_static_file("no_preview.png")


@serve.route("/thumbnail/<video_id>.png")
@cache.memoize(timeout=360)
def get_thumbnail_image_url(video_id=""):
    video = Video.query.filter_by(video_id=video_id).first()
    if video:
        if os.path.isfile(os.path.join(current_app.config["THUMBNAIL_FOLDER"], video_id + "_thumb_blurred.png")):
            for ct in video.tags:
                if ct.category > 1:
                    return send_from_directory(current_app.config["THUMBNAIL_FOLDER"], video_id + "_thumb_blurred.png")
        if os.path.isfile(os.path.join(current_app.config["THUMBNAIL_FOLDER"], video_id + "_thumb.png")):
            return send_from_directory(current_app.config["THUMBNAIL_FOLDER"], video_id + "_thumb.png")

    return serve.send_static_file("no_thumbnail.png")


@serve.route("/get_torrent")
def serve_torrent():
    torrent_path = os.path.join(media_path, TORRENT_NAME)
    if os.path.isfile(torrent_path):
        return send_from_directory(media_path, TORRENT_NAME, as_attachment=True)
    flash("Unable to get torrent file at this time", "error")
    return redirect(url_for("serve.front_page"))


@serve.route("/favicon.ico")
def serve_favicon():
    return url_for("serve.static", filename="favicon.ico")


@serve.route("/check_progress/<video_id>", methods=["GET"])
def check_progress(video_id):
    metadata = get_metadata_for_video(video_id)

    if not len(metadata.keys()):
        return "", 404

    if "duplicate" in metadata.keys():
        if len(metadata["duplicate"]):
            video_id = metadata["duplicate"]
            metadata = get_metadata_for_video(video_id)

    s = metadata["status"]
    if s == STATUS_COMPLETED:
        return "", 200
    if s == STATUS_DOWNLOADING:
        return "", 206
    if s == STATUS_FAILED:
        return "", 200
    if s == STATUS_INVALID or s == STATUS_COOKIES:
        return "", 415

    return abort(500)


@serve.route("/check_status")
@cache.cached(timeout=10)
def check_status():
    active_tasks = get_celery_active()
    scheduled_tasks = get_celery_scheduled()
    total_videos = Video.query.count()
    return {
        "active": len(active_tasks) if active_tasks else 0,
        "scheduled": len(scheduled_tasks) if scheduled_tasks else 0,
        "total_videos": total_videos
    }


def delete_video_by_id(video_id: str) -> bool:
    success = 0
    v = Video.query.filter_by(video_id=video_id).first()
    if v:
        remove_video_data(v)
        success += 1
        db_session.delete(v)
        db_session.commit()

    if os.path.isfile(os.path.join(media_path, video_id + ".mp4")):
        try:
            os.remove(os.path.join(media_path, video_id + ".mp4"))
            success += 1
        except OSError as e:
            flash(f"Failed to delete .mp4 file! {str(e)}", "error")
    if os.path.isfile(os.path.join(media_path, video_id + ".json")):
        try:
            os.remove(os.path.join(media_path, video_id + ".json"))
            success += 1
        except OSError as e:
            flash(f"Failed to delete .json file! {str(e)}", "error")

    if success < 3:
        logger.error(f"Might be some residue after video removal for {video_id}")
    if success > 0:
        logger.info(f"Deleted video {video_id} successfully.")
        return True
    return False


def list_videos(max_count=10) -> list:
    videos = []
    try:
        if max_count > 0:
            db_videos = Video.query.order_by(Video.upload_time.desc()).limit(max_count).all()
        else:
            db_videos = Video.query.order_by(Video.upload_time.desc()).all()

    except OperationalError:
        logger.error("DB operational error, probably doesn't exist.")
        db_videos = []

    if not len(db_videos):
        logger.warning("No videos from database?!")

    for v in db_videos:
        d = v.to_json()
        d["upload_time"] = v.upload_time.strftime("%Y-%m-%d %H:%M:%S")
        videos.append(d)

    return videos


@cache.memoize(timeout=1)
def get_metadata_for_video(video_id: str) -> dict:
    session = db_session
    try:
        video = Video.query.filter_by(video_id=video_id).first()
    except OperationalError:
        video = None

    if video:
        index_video_data(video)
        return video.to_json()

    path = os.path.join(media_path, video_id + ".json")
    try:
        with open(path) as f:
            d = json.load(f)

            if "video_id" not in d:
                d["video_id"] = video_id

            if not len(d["video_id"]):
                d["video_id"] = video_id

            if not video:
                video = Video()

            video.from_json(d)

            if "duplicate" in d:
                og_id = d["duplicate"]
                if len(og_id):
                    og = session.query(Video).filter_by(video_id=og_id).first()
                    if og:
                        if video.duplicate_of == og:
                            pass
                        elif video not in og.duplicates:
                            og.duplicates.append(video)
                            video.duplicate_of = og
                            session.add(og)

            session.add(video)
            logger.info(f"Found json file for {video_id}, returning metadata")

            index_video_data(video)
            d = video.to_json()

            try:
                session.commit()
            except OperationalError:
                session.rollback()
                logger.warning(f"Database connection seems bad, returning pure json data")
            except IntegrityError:
                session.rollback()
                logger.warning(f"Integrity error on writing to database, most likely duplicate video_id")
            except Exception as e:
                logger.error(e)

            return d

    except (FileNotFoundError, json.JSONDecodeError):
        logger.error(f"Error happened while loading JSON data for {video_id}")
        pass
    except OSError:
        logger.error(f"Error happened while opening files during fetching of metadata for {video_id}")
    return {}
