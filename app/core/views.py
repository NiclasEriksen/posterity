import os
import requests
from flask import Blueprint, current_app, request, abort, Response
from flask_login import current_user, login_required
from werkzeug.local import LocalProxy
from authentication import require_appkey
from urllib.parse import urlparse

from .tasks import download_task, post_process_task
from app.dl import STATUS_DOWNLOADING, STATUS_PENDING, STATUS_FAILED, STATUS_COMPLETED, STATUS_PROCESSING
from app.dl.helpers import unique_filename, remove_emoji, valid_video_url, minimize_url
from app.dl.metadata import parse_input_data, find_duplicate_video_by_url, get_title_from_html, API_SITES, \
    get_title_from_api, get_description_from_api
from app.serve.db import db_session, Video, AUTH_LEVEL_EDITOR

core = Blueprint('core', __name__)
logger = LocalProxy(lambda: current_app.logger)


@core.before_request
def before_request_func():
    current_app.logger.name = 'core'


@core.route("/test/<video_id>")
def test_desc(video_id: str):
    video = db_session.query(Video).filter_by(video_id=video_id).first()
    if not video:
        return "Video not found"
    title = get_description_from_api(video.url)
    return title


@core.route("/title_suggestion", methods=["POST"])
def title_suggestion():
    logger.info("Requested a title suggestion.")
    data = request.get_json()

    headers = {
        'Accept-Encoding': 'identity',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.75 Safari/537.36',
    }

    if "url" not in data:
        return Response("You need to supply an URL, dummy.", 418)

    url = minimize_url(data["url"])

    if not valid_video_url(url):
        return Response("Not a valid video url", status=406)

    if find_duplicate_video_by_url(url):
        return Response("Video with that URL exists", status=406)

    u = urlparse(url)

    if u.netloc in API_SITES:
        title = get_title_from_api(url)
    else:
        try:
            r = requests.get(url, headers=headers)
        except:
            logger.error("Unable to download page?!")
            return Response("Wasn't able to download the page and get a title.", 404)

        title = get_title_from_html(r.text)

    title = remove_emoji(title)

    return Response(title, 200)


@core.route("/start_processing/<video_id>", methods=["POST"])
def start_processing(video_id: str):
    if not current_user.is_authenticated:
        logger.error("Trying to start post-processing without being logged.")
        return Response("Lacking permissions to initiate processing task.", status=401)

    video = db_session.query(Video).filter_by(video_id=video_id).first()
    if not video:
        return Response("No video found by that id.", status=404)
    elif not current_user.check_auth(AUTH_LEVEL_EDITOR) and current_user.username is not video.source:
        logger.error("Trying to start post-processing without the right permissions.")
        return Response("Lacking permissions to initiate processing task.", status=401)
    if video.status == STATUS_DOWNLOADING:
        return Response("That video is currently downloading.", status=400)
    elif video.status == STATUS_PROCESSING:
        return Response("That video is already processing.", status=400)
    elif video.status == [STATUS_FAILED, STATUS_PENDING]:
        return Response("Video is not ready to be processed right now.", status=400)

    try:
        task_id = post_process_task.apply_async(args=[video.to_json(), video.video_id], priority=9)
    except Exception as e:
        video.status = STATUS_COMPLETED
        video.post_processed = False
        db_session.add(video)
        db_session.commit()
        logger.error(e)
        return Response("Error during adding of processing task.", status=400)
    else:
        video.status = STATUS_PROCESSING
        video.post_processed = False
        db_session.add(video)
        db_session.commit()
        logger.info(f"Started new processing task with id: {task_id}")
        return Response(f"/{video_id}", status=201)


@core.route("/start_download/<video_id>", methods=["POST"])
def start_download(video_id: str):
    if not current_user.is_authenticated:
        logger.error("Trying to start download without being logged in.")
        return Response("Lacking permissions to initiate download task.", status=401)
    video = db_session.query(Video).filter_by(video_id=video_id).first()
    if not video:
        return Response("No video found by that id.", status=404)
    if video.status == STATUS_DOWNLOADING:
        return Response("That video is already downloading.", status=400)
    elif video.status == STATUS_COMPLETED:
        return Response("That video is already downloaded.", status=400)

    try:

        task_id = download_task.apply_async(args=[video.to_json(), video.video_id], priority=1)
    except Exception as e:
        video.status = STATUS_PENDING
        db_session.add(video)
        db_session.commit()

        logger.error(e)
        return Response("Error during adding of download task. Link has been put back in pending queue.", status=400)
    else:
        video.status = STATUS_DOWNLOADING
        db_session.add(video)
        db_session.commit()

        logger.info(f"Started new download task with id: {task_id}")
        return Response(f"/{video_id}", status=201)


@core.route("/post_link", methods=["POST"])
def post_link():
    download_now = False

    logger.info("Link posted.")
    data = request.get_json()

    if current_user.is_authenticated:
        if "download_now" in data and isinstance(data["download_now"], bool):
            download_now = data["download_now"]
        else:
            download_now = True
        if "private-checkbox" in data and isinstance(data["private-checkbox"], bool):
            print("PRIVATE!!!!!")

        data["source"] = current_user.username
    else:
        data["source"] = "Anonymous"

    data = parse_input_data(data)

    if data and len(data.keys()):
        if "title" not in data:
            data["title"] = "No title"
        if not len(data["title"]):
            return Response("No title provided.", status=400)
        if "url" not in data:
            return Response("No url in posted data.", status=400)
        if not valid_video_url(data["url"]):
            return Response("That url doesn't seem valid.", status=400)
        if "private" in data and data["private"]:
            if not current_user.check_auth(AUTH_LEVEL_EDITOR):
                return Response("You don't have permissions to post private videos.", status=400)

        data["url"] = minimize_url(data["url"])

        if find_duplicate_video_by_url(data["url"]):
            return Response("Video with that URL exists", status=406)

        fn = unique_filename()

        try:
            existing = db_session.query(Video).filter_by(video_id=fn).first()
            if existing:
                return Response("Unable to make a unique id, weird...", status=400)
        except Exception as e:
            db_session.rollback()
            db_session.remove()
            logger.error(e)
            return Response("Unable to ensure that it's no duplicate, sorry...", status=400)

        data["video_id"] = fn

        try:
            video = Video()
            video.from_json(data)
            video.status = STATUS_PENDING
            db_session.add(video)
            db_session.commit()
        except Exception as e:
            db_session.rollback()
            db_session.remove()
            logger.error(e)
            logger.error("Failure to create video object in database.")
            return Response("Database error on adding video, weird.", status=400)

        if download_now:
            return start_download(fn)
        else:
            return Response("Video has peen submitted, pending approval.", status=202)

    return Response("No data posted.", status=400)


@core.route('/restricted', methods=['GET'])
@require_appkey
def restricted():
    return 'Congratulations! Your core-app restricted route is running via your API key!'
