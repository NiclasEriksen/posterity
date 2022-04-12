import functools
import os
from werkzeug.local import LocalProxy
from flask import current_app
from datetime import datetime
from elasticsearch import Elasticsearch, NotFoundError
from elastic_transport import ConnectionError, ConnectionTimeout
from .db import Video
from app.extensions import cache


es = Elasticsearch(os.environ.get("ES_SERVER_ADDRESS", "http://0.0.0.0:9200"))
log = LocalProxy(lambda: current_app.logger)

COMMON = [
    "talking", "about", "subtitles", "with", "without", "longer", "quality"
]


def catch_es_errors(f) -> []:
    @functools.wraps(f)
    def wrapper(*args, **kwargs) -> []:
        try:
            return f(*args, **kwargs)
        except (ConnectionError, ConnectionTimeout, NotFoundError, RuntimeError, OverflowError) as e:
            log.debug(e)
            log.error("Error during handling of ElasticSearch request, ignoring.")
            return []
    return wrapper


@catch_es_errors
def remove_videos_index():
    _result = es.indices.delete(index="videos", ignore=[400, 404])


@catch_es_errors
def remove_video_data(video: Video):
    _result = es.delete(index="videos", id=video.video_id)


@catch_es_errors
def remove_video_data_by_id(video_id: str):
    _result = es.delete(index="videos", id=video_id)


@catch_es_errors
def index_video_data(video: Video):
    body = {
        "title": video.title,
        "orig_title": video.orig_title,
        "url": video.url,
        "content_warning": video.content_warning,
        "upload_date": datetime.timestamp(video.upload_time),
        "source": video.source,
        "location": video.location
    }

    _result = es.index(index="videos", id=video.video_id, body=body)


@catch_es_errors
@cache.memoize(60)
def recommend_videos(video, size=10) -> list:
    fields = ["title", "orig_title", "content_warning"]
    t = video.title.lower()
    for c in COMMON:
        t.replace(c, "")
    q = f"""
    {t} {' '.join([t.name for t in video.tags])} {video.orig_title}
    """
    body = {
        "size": size,
        "query": {
            "bool": {
                "should": [
                    {
                        "multi_match": {
                            "query": q,
                            "fields": fields,
                            "fuzziness": "AUTO",
                            "prefix_length": 4,
                            "boost": 5
                        }
                    },
                    {
                        "more_like_this": {
                            "fields": fields,
                            "like": [
                                {
                                    "_index": "videos",
                                    "_id": video.video_id
                                },
                            ],
                            "min_term_freq": 1,
                            "max_query_terms": 24,
                            "boost": 3
                        }
                    },
                ]
            }
        }
    }

    res = es.search(index="videos", body=body)
    return res["hits"]["hits"]


@catch_es_errors
@cache.memoize(10)
def search_videos(keyword: str, size=100) -> list:

    fields = ["title", "orig_title", "content_warning"]
    body = {
        "size": size,
        "query": {
            "bool": {
                "must": [
                    {
                        "multi_match": {
                            "query": keyword,
                            "fields": fields,
                            "fuzziness": "AUTO",
                            "prefix_length": 4
                        }
                    }
                ],
                "should": [
                    {
                        "multi_match": {
                            "query": keyword,
                            "fields": fields,
                            "type": "phrase",
                            "boost": 10
                        }
                    },
                    {
                        "multi_match": {
                            "query": keyword,
                            "fields": fields,
                            "type": "phrase",
                            "boost": 5
                        }
                    },
                    {
                        "multi_match": {
                            "query": keyword,
                            "fields": fields,
                            "operator": "and",
                            "fuzziness": "AUTO",
                            "prefix_length": 4,
                            "boost": 3
                        }
                    }
                ]
            }
        }
    }

    res = es.search(index="videos", body=body)

    return res["hits"]["hits"]
