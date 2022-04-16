import pytz
from feedgen.feed import FeedGenerator
from flask import make_response, Blueprint, current_app, request
from sqlalchemy import or_, not_
from werkzeug.local import LocalProxy

from app.dl import STATUS_COMPLETED
from app.serve.db import Video, db_session, ContentTag, Category

feeds = Blueprint(
    'feeds', __name__,
    template_folder="templates",
    static_folder="../serve/static",
    static_url_path="/serve-static"
)
logger = LocalProxy(lambda: current_app.logger)


@feeds.route('/rss')
def rss():
    content_tag = request.args.get("t", "")
    category_tag = request.args.get("c", "")
    ignore_content_tag = request.args.get("it", "")
    ignore_category_tag = request.args.get("ic", "")

    fg = FeedGenerator()
    title = "Posterity videos"
    if any([
        len(content_tag),
        len(category_tag),
        len(ignore_content_tag),
        len(ignore_category_tag)
    ]):
        title += ", filtered by: "
        title += ", ".join([
            t for t in [content_tag, category_tag, ignore_content_tag, ignore_category_tag] if len(t)
        ])

    fg.title(title)
    fg.description('Videos archived for posterity')
    fg.link(href='https://www.posterity.no')

    vq = db_session.query(Video).filter_by(verified=True).filter_by(private=False).filter_by(status=STATUS_COMPLETED)

    if len(content_tag):
        t = db_session.query(ContentTag).filter(or_(ContentTag.name==content_tag, ContentTag.stub==content_tag)).first()
        if t:
            vq = vq.filter(Video.tags.any(id=t.id))
    if len(category_tag):
        t = db_session.query(Category).filter(or_(Category.name==category_tag, Category.stub==category_tag)).first()
        if t:
            vq = vq.filter(Video.categories.any(id=t.id))
    if len(ignore_content_tag):
        t = db_session.query(ContentTag).filter(or_(ContentTag.name==ignore_content_tag, ContentTag.stub==ignore_content_tag)).first()
        if t:
            vq = vq.filter(not_(Video.tags.any(id=t.id)))
    if len(ignore_category_tag):
        t = db_session.query(Category).filter(or_(Category.name==ignore_category_tag, Category.stub==ignore_category_tag)).first()
        if t:
            vq = vq.filter(not_(Video.categories.any(id=t.id)))

    videos = vq.order_by(Video.upload_time.desc()).limit(30).all()

    txt = ", ".join([v.video_id for v in videos])

    for video in videos:
        fe = fg.add_entry()
        fe.title(video.title)
        fe.link(href=video.page_url)
        fe.description(video.orig_title)
        fe.guid(video.page_url, permalink=True)
        fe.pubDate(video.upload_time.replace(tzinfo=pytz.UTC))

    response = make_response(fg.rss_str())
    response.headers.set('Content-Type', 'application/rss+xml')

    return response
