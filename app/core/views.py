from flask import Blueprint, current_app, request, abort
from werkzeug.local import LocalProxy

from authentication import require_appkey

from .tasks import test_task, download_task
from app.dl.youtube import valid_youtube_url
from app.dl.helpers import unique_filename

core = Blueprint('core', __name__)
logger = LocalProxy(lambda: current_app.logger)


@core.before_request
def before_request_func():
    current_app.logger.name = 'core'


@core.route('/test', methods=['GET'])
def test():
    logger.info('app test route hit')
    test_task.delay()
    return 'Congratulations! Your core-app test route is running!'


@core.route("/post_link", methods=["POST"])
def post_link():
    logger.info("Link posted.")
    data = request.get_json()
    fn = unique_filename()
    if data:
        if not "url" in data:
            abort(400)
            return "No url in data."
        if not valid_youtube_url(data["url"]):
            abort(400)
            return "No valid url."
        download_task.delay(data, fn)
        print(request.url_root + fn)
        return "https://posterity.no/" + fn
    abort(400)
    return "No data posted."


@core.route('/restricted', methods=['GET'])
@require_appkey
def restricted():
    return 'Congratulations! Your core-app restricted route is running via your API key!'
