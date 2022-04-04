from flask import Blueprint, current_app, request, abort, Response
from werkzeug.local import LocalProxy

from authentication import require_appkey

from .tasks import download_task
from app.dl.youtube import valid_video_url, minimize_url
from app.dl.helpers import unique_filename
from app.dl.dl import parse_input_data, find_duplicate_video_by_url, STATUS_DOWNLOADING
from app.serve.db import db_session, Video

core = Blueprint('core', __name__)
logger = LocalProxy(lambda: current_app.logger)


@core.before_request
def before_request_func():
    current_app.logger.name = 'core'


@core.route("/post_link", methods=["POST"])
def post_link():
    logger.info("Link posted.")
    data = request.get_json()
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
            video.status = STATUS_DOWNLOADING
            db_session.add(video)
            db_session.commit()
        except Exception as e:
            db_session.rollback()
            db_session.remove()
            logger.error(e)
            logger.error("Failure to create video object in database.")
            return Response("Database error on adding video, weird.", status=400)

        try:
            task_id = download_task.delay(data, fn)
        except Exception as e:
            logger.error(e)
            return Response("Error during adding of download task.", status=400)

        logger.info(f"Started new download task with id: {task_id}")
        return Response(f"https://posterity.no/{fn}", status=200)

    return Response("No data posted.", status=400)


@core.route('/restricted', methods=['GET'])
@require_appkey
def restricted():
    return 'Congratulations! Your core-app restricted route is running via your API key!'
