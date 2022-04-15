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
    "talking", "about", "subtitles", "with", "without", "longer", "quality", "cnn", "video", "full version",
    "nexta", "rob lee", "how", "reportedly", "possibly", "possible", "footage"
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
        "content_warning": video.content_warning,
        "upload_date": datetime.timestamp(video.orig_upload_time if video.orig_upload_time else video.upload_time),
        "source": video.source,
    }

    _result = es.index(index="videos", id=video.video_id, body=body)


@catch_es_errors
def index_all_videos():
    from app.serve.db import session_scope, Video
    with session_scope() as session:
        videos = session.query(Video).filter_by(private=False).all()
        for v in videos:
            index_video_data(v)



@catch_es_errors
@cache.memoize(60)
def recommend_videos(video, size=10) -> list:
    fields = ["title", "orig_title", "content_warning"]
    if video.title:
        title = video.title.lower()
    else:
        title = ""

    if video.orig_title:
        orig_title = video.orig_title.lower()
    else:
        orig_title = ""

    for c in COMMON:
        title = title.replace(c, "")
    for c in COMMON:
        orig_title = orig_title.replace(c, "")
    q = f"""
    {title} {' '.join([t.name for t in video.tags])} {orig_title}
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
        },
        "aggregations": {
            "rare_sample": {
                "sampler": {
                    "shard_size": 10,
                },
                "aggregations": {
                    "keywords": {
                        "significant_text": {
                            "field": "title"
                        }
                    }
                }
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
        },
        "aggregations": {
            "rare_sample": {
                "sampler": {
                    "shard_size": 100,
                },
                "aggregations": {
                    "keywords": {
                        "significant_text": {
                            "field": "title"
                        }
                    }
                }
            }
        }
    }

    res = es.search(index="videos", body=body)
    return res["hits"]["hits"]
