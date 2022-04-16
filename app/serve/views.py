import os
import functools
import re
import mimetypes
from dotenv import load_dotenv
import json
from datetime import datetime
from flask import Blueprint, current_app, request, abort,\
    render_template, send_from_directory, url_for, flash,\
    redirect, get_flashed_messages, Response
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import login_user, login_required, logout_user, current_user
from redis.exceptions import ConnectionError
from sqlalchemy.exc import OperationalError, IntegrityError
from werkzeug.local import LocalProxy
from sqlalchemy import or_, and_

serve = Blueprint(
    'serve', __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/serve-static"
)
logger = LocalProxy(lambda: current_app.logger)

from app.dl import media_path, original_path, json_path, processed_path, \
    STATUS_COMPLETED, STATUS_COOKIES, STATUS_DOWNLOADING, STATUS_FAILED, STATUS_INVALID, \
    STATUS_PROCESSING, STATUS_PENDING
from app.dl.dl import get_celery_scheduled, get_celery_active
from app.dl.metadata import write_metadata_to_disk, get_progress_for_video
from app.dl.helpers import seconds_to_verbose_time
from app.serve.db import db_session, Video, User, ContentTag, UserReport, Category,\
    init_db, AUTH_LEVEL_ADMIN, AUTH_LEVEL_EDITOR, AUTH_LEVEL_USER, REASON_TEXTS,\
    RegisterToken, MAX_TOKEN_USES
from app import get_environment
from app.serve.search import search_videos, index_video_data, remove_video_data, remove_video_data_by_id, \
    recommend_videos
from app.extensions import cache
from app.core.tasks import gen_images_task, check_all_duplicates_task, \
    COMPARE_DURATION_THRESHOLD, COMPARE_RATIO_THRESHOLD, COMPARE_IMAGE_DATA_THRESHOLD


# Setup
init_db()
load_dotenv()
APPLICATION_ENV = get_environment()
MAX_RESULT_PER_PAGE = 30
MAX_RELATED_VIDEOS = 8
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


@serve.after_request
def after_request(response):
    response.headers.add('Accept-Ranges', 'bytes')
    return response


@serve.context_processor
def inject_status_codes_for_all_templates():
    return dict(
        STATUS_DOWNLOADING=STATUS_DOWNLOADING,
        STATUS_COMPLETED=STATUS_COMPLETED,
        STATUS_FAILED=STATUS_FAILED,
        STATUS_INVALID=STATUS_INVALID,
        STATUS_COOKIES=STATUS_COOKIES,
        STATUS_PENDING=STATUS_PENDING,
        STATUS_PROCESSING=STATUS_PROCESSING,
        AUTH_LEVEL_USER=AUTH_LEVEL_USER,
        AUTH_LEVEL_EDITOR=AUTH_LEVEL_EDITOR,
        AUTH_LEVEL_ADMIN=AUTH_LEVEL_ADMIN
    )

@serve.route('/robots.txt')
@serve.route('/sitemap.xml')
def static_from_root():
    return send_from_directory(serve.static_folder, request.path[1:])


@serve.route("/", methods=["GET"])
def front_page():
    page = request.args.get("p", type=int, default=1)
    pp = request.args.get("pp", type=int, default=MAX_RESULT_PER_PAGE)
    kw = request.args.get("q", type=str, default="")
    t = request.args.get("t", type=int, default=-1)
    c = request.args.get("c", type=int, default=-1)

    tag = None
    if t >= 0:
        tag = db_session.query(ContentTag).filter_by(id=t).first()
    category = None
    if c >= 0:
        category = db_session.query(Category).filter_by(id=c).first()

    offset = max(0, page - 1) * pp

    if len(kw):
        logger.info(f"Searching for {kw}.")
        results = search_videos(kw)
        results = sorted(results, key=lambda x: x["_score"], reverse=True)
        # logger.info(results)

        total = len(results)
        videos = []
        removed = 0
        for result in results:
            vq = Video.query.filter_by(video_id=result["_id"])
            v = vq.first()
            if v:
                if (tag and not tag in v.tags) or (category and not category in v.categories):
                    removed += 1
                elif not v.user_can_see(current_user):
                    removed += 1
                else:
                    videos.append(v)
            else:
                removed += 1
                remove_video_data_by_id(result["_id"])
        videos = videos[offset: offset + MAX_RESULT_PER_PAGE]

        total -= removed

    else:
        vq = db_session.query(Video)

        if category:
            vq = vq.filter(Video.categories.any(id=category.id))
        if tag:
            vq = vq.filter(Video.tags.any(id=tag.id))

        vq = vq.order_by(
            Video.upload_time.desc()
        )
        all_videos = [v for v in vq.all() if v.user_can_see(current_user)]
        total = len(all_videos)
        videos = all_videos[offset: offset + MAX_RESULT_PER_PAGE]

    total_pages = total // pp + (1 if total % pp else 0)

    available_tags = ContentTag.query.order_by(ContentTag.category.desc(), ContentTag.name).all()
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
        search_tag=tag,
        search_category=category,
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

    video = Video.query.filter_by(video_id=video_id).first()

    if not video:
        logger.error("Video was not found.")
        return render_template("not_found.html")

    try:
        results = recommend_videos(video, size=MAX_RELATED_VIDEOS * 2)
        results = sorted(results, key=lambda x: x["_score"], reverse=True)
    except Exception as e:
        logger.error(e)
        logger.error("Unable to get recommendations for video, error above.")
        results = []

    recommended = []
    for result in results:
        v = Video.query.filter_by(video_id=result["_id"]).first()
        if v and not v == video:
            if v.user_can_see(current_user):
                recommended.append(v)

    recommended = recommended[:MAX_RELATED_VIDEOS]

    if "embed" in request.args:
        return render_template(
            "embed_video.html",
            video=video,
            stream_path=f"/view/{video_id}.mp4"
        )

    return render_template(
        "video.html",
        video=video,
        dl_path="/download/" + video_id,
        recommended=recommended,
        stream_path=f"/view/{video_id}.mp4" + ("?orig=1" if video.status == STATUS_PROCESSING else ""),
    )


@serve.route("/edit_video/<video_id>", methods=["GET"])
@login_required
def edit_video_page(video_id: str):
    video: Video = Video.query.filter_by(video_id=video_id).first()
    if not video:
        return render_template("not_found.html")

    if not video.user_can_edit(current_user):
        flash("Lacking permissions to edit that video.", "error")
        return serve_video(video.video_id)
    if video.status == STATUS_DOWNLOADING:
        flash("Can't edit video right now, sorry.", "warning")
        return serve_video(video.video_id)


    available_tags = ContentTag.query.order_by(ContentTag.category.desc(), ContentTag.name).all()
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
        video=video,
        tags=available_tags,
        categories=available_categories,
    )


@serve.route("/edit_video/<video_id>", methods=["POST"])
@login_required
def edit_video_post(video_id: str):
    video: Video = Video.query.filter_by(video_id=video_id).first()
    if not video:
        return render_template("not_found.html")

    if not video.user_can_edit(current_user):
        flash("Lacking permissions to edit that video.", "error")
        return serve_video(video.video_id)

    title = request.form.get("custom_title")
    description = request.form.get("description")
    private = request.form.get("private-checkbox")
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

    if video.status != STATUS_DOWNLOADING:
        video.title = title
        video.orig_title = description

    video.private = True if private == "on" else False

    db_session.add(video)
    db_session.commit()
    write_metadata_to_disk(video_id, video.to_json())
    index_video_data(video)

    if video.ready_to_play:
        try:
            _task_id = gen_images_task.apply_async(args=[video.to_json()], priority=0)
        except Exception as e:
            logger.error(e)

    flash(f"Video info for \"{video_id}\"has been updated.", "success")

    return redirect(url_for("serve.serve_video", video_id=video.video_id))


@serve.route("/register", methods=["GET"])
def register_user_page():
    token = request.args.get("token", default="")
    if current_user.is_authenticated:
        flash(f"You already have an account. Log out in order to register a new one.")
        return redirect(url_for("serve.front_page"))
    return render_template("register.html", token=token)


@serve.route("/register", methods=["POST"])
def register_user_post():
    username = request.form.get("username")
    password = request.form.get("password")
    token = request.form.get("token")

    existing_token = db_session.query(RegisterToken).filter_by(token=token).first()

    if not existing_token:
        flash(f"Invalid token for user registration.", "error")
        logger.error(f"Invalid token for user registration.")
        return redirect(url_for("serve.register_user_page", token=token))

    if not len(password) >= 6:
        flash("Password needs to be 6 characters or longer.", "error")
        return redirect(url_for("serve.register_user_page", token=token))
    
    if not len(username) >= 3:
        flash("Username needs to be 3 characters or longer.", "error")
        return redirect(url_for("serve.register_user_page", token=token))

    existing_user = User.query.filter_by(username=username).first()
    if existing_user or username == "Anonymous":
        flash("Username already taken, please choose another one.", "error")
        return redirect(url_for("serve.register_user_page", token=token))

    if not existing_token.is_valid():
        flash("That token is expired or spent and can no longer be used.", "error")
        return redirect(url_for("serve.register_user_page", token=token))

    existing_token.spend_token()

    password_hash = generate_password_hash(password)

    user = User()
    user.username = username
    user.password = password_hash
    user.auth_level = existing_token.auth_level

    db_session.add(existing_token)
    db_session.add(user)
    db_session.commit()

    login_user(user, remember=True)
    flash(f"User registered and logged in. Welcome to Posterity!", "success")

    return redirect(url_for("serve.front_page"))


@serve.route("/logout")
@login_required
def logout_route():
    logout_user()
    next_target = request.args.get("next", "/")
    flash("You have been logged out.", "success")
    return redirect(next_target)


@serve.route("/login", methods=["GET"])
def login_page():
    if current_user.is_authenticated:
        flash(f"You are already logged in.", "error")
        return redirect(url_for("serve.front_page"))

    next_target = request.args.get("next", "/")
    get_flashed_messages()
    return render_template("login.html", next_target=next_target)


@serve.route("/login", methods=["POST"])
def login_post_route():
    username = request.form.get("username")
    password = request.form.get("password")

    next_target = request.args.get("next", "/")

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
    return redirect(next_target)


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


@serve.route("/dashboard")
@login_required
def dashboard_page():
    tokens = db_session.query(RegisterToken).filter(RegisterToken.auth_level <= current_user.auth_level).all()
    other_users = db_session.query(User).filter(
        User.auth_level <= current_user.auth_level
    ).filter(
        User.id != current_user.id
    ).order_by(User.id).all()

    for u in other_users:
        u.uploaded = db_session.query(Video).filter_by(source=u.username).count()

    current_tasks = []

    q = db_session.query(Video).filter(
        or_(Video.status != STATUS_COMPLETED, Video.user_reports.any())
    )

    current_tasks = q.order_by(
        Video.status
    ).all()
    if not current_user.check_auth(AUTH_LEVEL_EDITOR):
        current_tasks = [v for v in current_tasks if v.user_can_see(current_user)]

    possible_duplicates = list_all_duplicates()
    possible_duplicates = [v for v in possible_duplicates if v.user_can_see(current_user)]
    pairs = []
    paired = {}
    for v in possible_duplicates:
        for d in v.pending_duplicates:
            if d.video_id in paired:
                if v.video_id in paired[d.video_id]:
                    continue
            pairs.append((v, d))
            if v.video_id not in paired:
                paired[v.video_id] = []
            if d.video_id not in paired:
                paired[d.video_id] = []
            paired[v.video_id].append(d.video_id)
            paired[d.video_id].append(v.video_id)

    pairs = pairs[:50]

    for ct in current_tasks:
        ct.progress = "{0:.0f}%".format(get_progress_for_video(ct) * 100.0)

    return render_template(
        "dashboard.html",
        user=current_user, tokens=tokens, other_users=other_users,
        tasks=current_tasks, duplicates=pairs
    )


@serve.route("/about", methods=["GET"])
def about_us_page():
    return render_template("about.html", total_time=seconds_to_verbose_time(get_total_duration()))


@serve.route("/remove/<video_id>")
@login_required
def remove_video_route(video_id):
    video = db_session.query(Video).filter_by(video_id=video_id).first()

    if video:
        if not video.user_can_edit(current_user):
            flash("You don't have permission to remove that video.", "error")
        else:
            success = delete_video_by_id(video_id)
            if not success:
                flash("Error during removal of video, might be some residue.", "warning")
                return redirect(url_for("serve.edit_video_page", video_id=video_id))
            else:
                flash(f"Video \"{video_id}\" has been deleted successfully!", "success")
    else:
        flash("No video by that id, nothing to remove.", "error")

    return redirect(url_for("serve.front_page"), code=302)


@serve.route("/report_video/<video_id>", methods=["GET"])
def report_video_route(video_id):
    video = db_session.query(Video).filter_by(video_id=video_id).first()
    if not video:
        return render_template("not_found.html")
    if video.private and not video.user_can_edit(current_user):
        return render_template("private.html")

    report_reasons = [{"id": k, "text": v} for k, v in REASON_TEXTS.items()]

    return render_template("report_video.html", video=video, report_reasons=report_reasons)


@serve.route("/report_video/<video_id>", methods=["POST"])
def report_video_post(video_id):
    video = db_session.query(Video).filter_by(video_id=video_id).first()
    if not video:
        return render_template("not_found.html")
    if video.private and not video.user_can_edit(current_user):
        return render_template("private.html")

    text = request.form.get("report_text", "")
    reason = request.form.get("report_reason")

    try:
        reason = int(reason)
        assert reason in REASON_TEXTS.keys()
    except (TypeError, ValueError, AssertionError):
        flash("Invalid data in report form, it was not submitted.", "error")
        return report_video_route(video_id)

    user_report = UserReport(video, reason, text, current_user.username)
    db_session.add(user_report)
    db_session.commit()

    flash("Video has been reported to the editors. Thank you!", "success")
    return redirect(url_for("serve.serve_video", video_id=video.video_id))


@serve.route("/clear_report/<report_id>", methods=["GET"])
@login_required
def clear_report_route(report_id):
    try:
        report_id = int(report_id)
    except (ValueError, TypeError):
        return render_template("not_found.html", type="report")
    report = db_session.query(UserReport).filter_by(id=report_id).first()
    if not report:
        return render_template("not_found.html", type="report")

    video = report.video
    if video:
        video_id = video.video_id
    else:
        video_id = ""

    db_session.delete(report)
    db_session.commit()
    flash("User report has been deleted.", "success")

    return redirect(url_for("serve.serve_video", video_id=video.video_id))


@serve.route("/clear_duplicate", methods=["GET"])
@login_required
def clear_duplicate_route():
    v1 = request.args.get("v1", "")
    v2 = request.args.get("v2", "")

    if not len(v1) or not len(v2):
        flash("Missing one or both video ids to clear for duplicate", "warning")
        return redirect(url_for("serve.dashboard_page"))
    if any(x in v1 + v2 for x in ";/:\\&_"):
        flash("Invalid characters in video ids", "warning")
        return redirect(url_for("serve.dashboard_page"))

    video1 = db_session.query(Video).filter_by(video_id=v1).first()
    video2 = db_session.query(Video).filter_by(video_id=v2).first()

    if not video1 or not video2:
        flash("One or both of the video ids are invalid", "warning")
        return redirect(url_for("serve.dashboard_page"))

    if video2 in video1.duplicates:
        video1.duplicates.remove(video2)
        video1.false_positives.append(video2)
    if video1 in video2.duplicates:
        video2.duplicates.remove(video1)
        video2.false_positives.append(video1)
    db_session.add(video1, video2)
    db_session.commit()
    flash("Duplicate link cleared", "success")
    return redirect(url_for("serve.dashboard_page"))


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
    video = db_session.query(Video).filter_by(video_id=video_id).first()
    orig = request.args.get("orig", 1)

    if not video:
        return Response(render_template("not_found.html"), 404)

    if orig == 0:
        first_p = processed_path
        last_p = original_path
    else:
        first_p = original_path
        last_p = processed_path

    try:
        if os.path.isfile(os.path.join(first_p, video_id + ".mp4")):
            return send_from_directory(first_p, video_id + ".mp4", as_attachment=True, conditional=True)
        elif os.path.isfile(os.path.join(last_p, video_id + ".mp4")):
            return send_from_directory(last_p, video_id + ".mp4", as_attachment=True, conditional=True)
    except OSError as e:
        logger.error(e)
        logger.error("Unable to serve video!")
    return Response(render_template("not_found.html"), 404)


@serve.route("/view/<video_id>.mp4")
def view_video(video_id=""):
    original = request.args.get("orig", type=int, default=0)
    processed = False
    try:
        video = db_session.query(Video).filter_by(video_id=video_id).first()
    except Exception as e:
        logger.error(e)
    else:
        processed = video.post_processed

    try:
        if processed and not original:
            proc_path = os.path.join(processed_path, f"{video_id}.mp4")
            if os.path.isfile(proc_path):
                return send_from_directory_partial(processed_path, f"{video_id}.mp4")
        if os.path.isfile(os.path.join(original_path, f"{video_id}.mp4")):
            return send_from_directory_partial(original_path, f"{video_id}.mp4")
    except OSError as e:
        logger.error(e)
        logger.error("Unable to serve video!")
    return "Video file not found."


@serve.route("/preview/<video_id>.jpg")
def get_preview_image(video_id=""):
    video = Video.query.filter_by(video_id=video_id).first()
    try:
        if video:
            if os.path.isfile(os.path.join(current_app.config["PREVIEW_FOLDER"], video_id + "_preview_blurred.jpg")):
                for ct in video.tags:
                    if ct.category > 1:
                        return send_from_directory(current_app.config["PREVIEW_FOLDER"], video_id + "_preview_blurred.jpg")
            if os.path.isfile(os.path.join(current_app.config["PREVIEW_FOLDER"], video_id + "_preview.jpg")):
                return send_from_directory(current_app.config["PREVIEW_FOLDER"], video_id + "_preview.jpg")
    except Exception as e:
        logger.error(e)
        logger.error("Unhandled exception during fetching of preview image.")

    return serve.send_static_file("no_preview.jpg")


@serve.route("/thumbnail/<video_id>.jpg")
def get_thumbnail_image(video_id=""):
    try:
        video = Video.query.filter_by(video_id=video_id).first()
        if video:
            if os.path.isfile(os.path.join(current_app.config["THUMBNAIL_FOLDER"], video_id + "_thumb_blurred.jpg")):
                for ct in video.tags:
                    if ct.category > 1:
                        return send_from_directory(current_app.config["THUMBNAIL_FOLDER"], video_id + "_thumb_blurred.jpg")
            if os.path.isfile(os.path.join(current_app.config["THUMBNAIL_FOLDER"], video_id + "_thumb.jpg")):
                return send_from_directory(current_app.config["THUMBNAIL_FOLDER"], video_id + "_thumb.jpg")
    except Exception as e:
        logger.error(e)
        logger.error("Unhandled exception during fetching of thumbnail image.")

    return serve.send_static_file("no_thumbnail.jpg")


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
@cache.memoize(timeout=1)
def check_progress(video_id):
    video = Video.query.filter_by(video_id=video_id).first()

    if not video:
        return "", 404

    s = video.status
    if s == STATUS_COMPLETED or s == STATUS_PENDING:
        if video.post_processed:
            flash("Post processing seems to have completed successfully", "success")
            return "", 201
        # if s == STATUS_COMPLETED:
        #     flash("Video has downloaded successfully", "success")
        return "", 200
    if s == STATUS_DOWNLOADING or s == STATUS_PROCESSING:
        p = get_progress_for_video(video)
        return f"{p}", 206
    if s == STATUS_FAILED:
        return "", 200
    if s == STATUS_INVALID or s == STATUS_COOKIES:
        return "", 415

    flash("This error shouldn't happen, it means we haven't accounted for a status", "error")
    return abort(500)


@serve.route("/check_duplicates/<video_id>", methods=["GET"])
@login_required
def check_duplicates_route(video_id: str):
    video = db_session.query(Video).filter_by(video_id=video_id).first()

    if video and video.status == STATUS_COMPLETED:
        duplicate_ids = get_possible_duplicates(video_id)
        duplicates = []

        for d_id in duplicate_ids:
            v = db_session.query(Video).filter_by(video_id=d_id).first()
            if v:
                duplicates.append(v)

        for vd in video.duplicates:
            if vd not in duplicates:
                video.duplicates.remove(vd)
        for d in duplicates:
            if d not in video.duplicates:
                video.duplicates.append(d)

        db_session.add(video)
        db_session.commit()

        if len(duplicates):
            flash(f"{len(duplicates)} potential duplicates was found.", "warning")
        else:
            flash("No potential duplicates was found.", "success")
    else:
        flash("Video not ready to check for duplicates.", "error")

    return serve_video(video_id)


@serve.route("/check_all_duplicates", methods=["GET"])
@login_required
@cache.cached(timeout=30)
def check_all_duplicates_route():
    if not current_user.check_auth(AUTH_LEVEL_EDITOR):
        flash("You're lacking permissions to do that.", "error")
        return redirect(url_for("serve.dashboard_page"))

    check_all_duplicates_task.delay()

    flash("Started full duplicate check, check back in a minute.", "success")

    return redirect(url_for("serve.dashboard_page"))


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


@serve.route("/dashboard/create_token", methods=["POST"])
@login_required
def create_token_route():
    name = request.form.get("token_name", default="New token")
    auth_level = request.form.get("auth_level", default=0)
    uses = request.form.get("token_uses", default=1)

    try:
        auth_level = int(auth_level)
    except (ValueError, TypeError):
        auth_level = 0
    try:
        uses = int(uses)
    except (ValueError, TypeError):
        uses = 0

    if auth_level > current_user.auth_level or auth_level < 0:
        flash("Invalid auth level given.", "error")
        return redirect(url_for("serve.dashboard_page"))
    elif uses > MAX_TOKEN_USES or not uses > 0:
        flash("Invalid number of uses given.", "error")
        return redirect(url_for("serve.dashboard_page"))

    try:
        token = RegisterToken(name, auth_level=auth_level, uses=uses)
        token.generate()
        db_session.add(token)
        db_session.commit()
    except Exception as e:
        flash("Database error during creation of token", "error")
        return redirect(url_for("serve.dashboard_page"))

    flash("Token has been created and is active", "success")
    return redirect(url_for("serve.dashboard_page"))


@serve.route("/dashboard/delete_token/<token_id>", methods=["GET"])
@login_required
def delete_token_route(token_id):
    try:
        token_id = int(token_id)
    except (ValueError, TypeError):
        flash("Invalid token ID given", "error")
        return redirect(url_for("serve.dashboard_page"))

    token = db_session.query(RegisterToken).filter_by(id=token_id).first()

    if not token:
        flash("Token not found, aborting.", "error")
        return redirect(url_for("serve.dashboard_page"))

    if token.auth_level > current_user.auth_level:
        flash("You don't have permissions to delete that token.", "error")
        return redirect(url_for("serve.dashboard_page"))

    try:
        db_session.delete(token)
        db_session.commit()
    except Exception as e:
        logger.error(e)
        flash("Database error under deletion of token", "error")
        return redirect(url_for("serve.dashboard_page"))

    flash("Token has been deleted and is no longer active", "success")
    return redirect(url_for("serve.dashboard_page"))


def delete_video_by_id(video_id: str) -> bool:
    success = 0
    v = Video.query.filter_by(video_id=video_id).first()
    if v:
        remove_video_data(v)
        success += 1
        db_session.delete(v)
        db_session.commit()

    if os.path.isfile(os.path.join(original_path, video_id + ".mp4")):
        try:
            os.remove(os.path.join(original_path, video_id + ".mp4"))
            success += 1
        except OSError as e:
            flash(f"Failed to delete .mp4 file! {str(e)}", "error")
    if os.path.isfile(os.path.join(processed_path, video_id + ".mp4")):
        try:
            os.remove(os.path.join(processed_path, video_id + ".mp4"))
            success += 1
        except OSError as e:
            flash(f"Failed to delete .mp4 file! {str(e)}", "error")
    if os.path.isfile(os.path.join(json_path, video_id + ".json")):
        try:
            os.remove(os.path.join(json_path, video_id + ".json"))
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


@cache.cached(timeout=60)
def get_total_duration() -> float:
    from sqlalchemy.sql import func
    total = 0.0
    try:
        q = db_session.query(func.sum(Video.duration).label("total_duration"))
    except Exception as e:
        logger.error(e)

    result = q.all()
    if len(result):
        total = result[0][0]

    return total


@cache.memoize(timeout=1)
def get_metadata_for_video(video_id: str) -> dict:
    try:
        video = Video.query.filter_by(video_id=video_id).first()
    except OperationalError:
        video = None

    if video:
        index_video_data(video)
        return video.to_json()
    return {}


def list_all_duplicates() -> list:
    try:
        return db_session.query(Video).filter(Video.duplicates.any()).order_by(
            Video.upload_time.desc()
        ).all()
    except Exception as e:
        logger.error(e)
        return []


@cache.memoize(timeout=60)
def get_possible_duplicates(video_id: str) -> list:
    try:
        from imgcompare import is_equal
        from PIL import Image
        candidates = []

        video = db_session.query(Video).filter_by(video_id=video_id).first()
        if not video:
            return candidates

        db_vids = db_session.query(Video).filter(Video.video_id != video_id).filter_by(status=STATUS_COMPLETED).all()

        duration_candidates = []

        vid_q = []
        for v in db_vids:
            if v not in video.false_positives and video not in v.false_positives:
                vid_q.append(v)

        for v in vid_q:
            if v.duration and video.duration:
                if abs(1.0 - v.duration / video.duration) <= COMPARE_DURATION_THRESHOLD:
                    duration_candidates.append(v)
                    continue

        aspect_ratio_candidates = []
        for v in duration_candidates:
            if abs(v.aspect_ratio - video.aspect_ratio) <= COMPARE_RATIO_THRESHOLD:
                aspect_ratio_candidates.append(v)
                continue

        vid_thumb_path = os.path.join(current_app.config["THUMBNAIL_FOLDER"], video_id + "_thumb.jpg")

        if os.path.isfile(vid_thumb_path):
            img_candidates = []
            for v in aspect_ratio_candidates:
                other_thumb_path = os.path.join(current_app.config["THUMBNAIL_FOLDER"], v.video_id + "_thumb.jpg")
                if os.path.isfile(other_thumb_path):
                    try:
                        img1 = Image.open(vid_thumb_path)
                        img2 = Image.open(other_thumb_path)
                        img1 = img1.resize((64, 64))
                        img2 = img2.resize((64, 64))
                        if is_equal(img1, img2, tolerance=COMPARE_IMAGE_DATA_THRESHOLD):
                            img_candidates.append(v)
                            continue
                    except Exception as e:
                        logger.error(e)
                        continue

            candidates = img_candidates
        else:
            candidates = aspect_ratio_candidates
        return [c.video_id for c in candidates]
    except Exception as e:
        logger.error(e)
        db_session.rollback()
        return []


def send_from_directory_partial(directory, filename):
    """
        Simple wrapper around send_file which handles HTTP 206 Partial Content
        (byte ranges)
        TODO: handle all send_file args, mirror send_file's error handling
        (if it has any)
    """
    range_header = request.headers.get('Range', None)
    if not range_header:
        return send_from_directory(directory, filename, conditional=True)

    path = os.path.join(directory, filename)
    size = os.path.getsize(path)
    byte1, byte2 = 0, None

    m = re.search('(\d+)-(\d*)', range_header)
    g = m.groups()

    if g[0]: byte1 = int(g[0])
    if g[1]: byte2 = int(g[1])

    length = size - byte1
    if byte2 is not None:
        length = byte2 - byte1

    data = None
    with open(path, 'rb') as f:
        f.seek(byte1)
        try:
            data = f.read(length)
        except ValueError:
            logger.error("Error when reading video file, length given is wrong.")
            data = b""

    rv = Response(data,
                  206,
                  mimetype=mimetypes.guess_type(path)[0],
                  direct_passthrough=True)
    rv.headers.add('Content-Range', 'bytes {0}-{1}/{2}'.format(byte1, byte1 + length - 1, size))

    return rv
