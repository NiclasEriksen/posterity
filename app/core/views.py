from flask import Blueprint, current_app, request, abort, Response
from flask_login import current_user, login_required
from werkzeug.local import LocalProxy

from authentication import require_appkey

from .tasks import download_task, post_process_task
from app.dl.youtube import valid_video_url, minimize_url
from app.dl.helpers import unique_filename
from app.dl.dl import parse_input_data, find_duplicate_video_by_url,\
    STATUS_DOWNLOADING, STATUS_PENDING, STATUS_FAILED, STATUS_COMPLETED, STATUS_PROCESSING
from app.serve.db import db_session, Video

core = Blueprint('core', __name__)
logger = LocalProxy(lambda: current_app.logger)


@core.before_request
def before_request_func():
    current_app.logger.name = 'core'


@core.route("/start_processing/<video_id>", methods=["POST"])
def start_processing(video_id: str):
    if not current_user.check_auth(1):
        logger.error("Trying to start post-processing without the right permissions.")
        return Response("Lacking permissions to initiate processing task.", status=401)

    video = db_session.query(Video).filter_by(video_id=video_id).first()
    if not video:
        return Response("No video found by that id.", status=404)
    if video.status == STATUS_DOWNLOADING:
        return Response("That video is currently downloading.", status=400)
    elif video.status == STATUS_PROCESSING:
        return Response("That video is already processing.", status=400)
    elif video.status == [STATUS_FAILED, STATUS_PENDING]:
        return Response("Video is not ready to be processed right now.", status=400)

    try:
        task_id = post_process_task.delay(video.to_json(), video.video_id)
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
        task_id = download_task.delay(video.to_json(), video.video_id)
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
