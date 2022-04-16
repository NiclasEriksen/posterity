from feedgen.feed import FeedGenerator
from flask import make_response, Blueprint
from werkzeug.local import LocalProxy

feeds = Blueprint(
    'feeds', __name__,
    template_folder="templates",
    static_folder="../serve/static",
    static_url_path="/serve-static"
)
logger = LocalProxy(lambda: current_app.logger)


@feeds.route('/rss')
def rss():
    fg = FeedGenerator()
    fg.title('Feed title')
    fg.description('Feed description')
    fg.link(href='https://awesome.com')

    for article in get_news(): # get_news() returns a list of articles from somewhere
        fe = fg.add_entry()
        fe.title(article.title)
        fe.link(href=article.url)
        fe.description(article.content)
        fe.guid(article.id, permalink=False) # Or: fe.guid(article.url, permalink=True)
        fe.author(name=article.author.name, email=article.author.email)
        fe.pubDate(article.created_at)

    response = make_response(fg.rss_str())
    response.headers.set('Content-Type', 'application/rss+xml')

    return response