from flask import Blueprint, current_app, request, abort, Response
from werkzeug.local import LocalProxy

from authentication import require_appkey

from .tasks import download_task
from app.dl.youtube import valid_youtube_url
from app.dl.helpers import unique_filename
from app.dl.dl import parse_input_data, find_duplicate_video_by_url
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
        fn = unique_filename()
        data["video_id"] = fn

        try:
            existing = db_session.query(Video).filter_by(video_id=fn).first()
        except Exception as e:
            db_session.rollback()
            db_session.remove()
            logger.error(e)
            existing = None

        if existing:
            return Response("Video with that ID exists", status=400)

        if "url" not in data:
            abort(400)
            return "No url in data."
        if not valid_youtube_url(data["url"]):
            abort(400)
            return "No valid url."
        if find_duplicate_video_by_url(data["url"]):
            return Response("Video with that URL exists", status=406)
            abort(400)
            return "Duplicate video."

        try:
            video = Video()
            video.from_json(data)
            db_session.add(video)
            db_session.commit()
        except Exception as e:
            db_session.rollback()
            db_session.remove()
            logger.error(e)
            logger.error("Failure to create video object in database.")
            abort(400)
            return "Database error on adding video, weird."

        try:
            task_id = download_task.delay(data, fn)
        except Exception as e:
            print(e)
            abort(400)
            return "Error during adding of download task."

        print("MAKING VIDEO")
        print(task_id)

        logger.info(f"Started new download task with id: {task_id}")
        return "https://posterity.no/" + fn

    abort(400)
    return "No data posted."


@core.route('/restricted', methods=['GET'])
@require_appkey
def restricted():
    return 'Congratulations! Your core-app restricted route is running via your API key!'
