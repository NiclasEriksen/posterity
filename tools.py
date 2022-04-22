import os
import praw
import requests
import socket
from time import time, sleep
import warnings
warnings.simplefilter(action='ignore', category=FutureWarning)
from app.dl.helpers import remove_links, remove_tags, remove_emoji, minimize_url
from app.dl.metadata import strip_useless

start = time()

# from parrot import Parrot
import dotenv
dotenv.load_dotenv()

socket.setdefaulttimeout(10)
from prawcore.exceptions import ResponseException

SUBREDDITS = [
    "ukraine", "combatfootage", "yemenvoice"
]
UKRAINE_KEYWORDS = ["ukraine", "putin", "russia", "russian", "ukrainian", "slava"]

reddit = praw.Reddit(
    client_id=os.environ.get("REDDIT_CLIENT_ID", ""),
    client_secret=os.environ.get("REDDIT_CLIENT_SECRET", ""),
    user_agent="Posterity title fetcher",
    username=os.environ.get("REDDIT_USER", ""),
    password=os.environ.get("REDDIT_PW", "")
)
# parrot = Parrot(model_tag="prithivida/parrot_paraphraser_on_T5")
dur1 = time() - start
print(f"{dur1:.2f} seconds to load parrot")
start = time()


def parse_subreddit_for_links(sr: str, limit: int = 10) -> list:
    subreddit = reddit.subreddit(sr)
    videos = []
    for submission in subreddit.new(limit=limit):
        if submission.is_video:
            videos.append({
                "title": submission.title,
                "desc": submission.selftext,
                "url": submission.url
            })
    return videos


def clean_up_api_results(videos: list) -> list:
    for video in videos:
        orig_title = video["title"]
        title = clean_up_text(video["title"])
        # sentences = [s.rstrip().lstrip() for s in cleaned.split(".")]
        # paraphrased = []
        # for s in sentences:
        #     paraphrased.append(paraphrase_text(s))
        # title = ". ".join([s for s in paraphrased if len(s)])
        if len(title):
            video["title"] = title
        else:
            video["title"] = "NOTITLE"
        print("========================")
        print("Original:")
        print(orig_title)
        print("Cleaned:")
        print(title)
        # print("Paraphrased:")
        # print(video["title"])
        print("========================")
    return videos


def remove_posted_videos(videos: list) -> list:
    result = {}
    try:
        r = requests.post("https://posterity.no/api/v1/core/check_if_exists", json={"videos": videos}, timeout=30)
        if r.status_code == 200:
            data = r.json()
            if data and len(data.keys()):
                result = data
    except Exception as e:
        print(e)
        return videos

    ok_videos = []
    for v in videos:
        if v["url"] in result:
            if result[v["url"]]:
                continue
        ok_videos.append(v)
    return ok_videos


def resolve_urls(videos: list) -> list:
    for v in videos:
        session = requests.Session()  # so connections are recycled
        try:
            resp = session.head(minimize_url(v["url"]), allow_redirects=True, timeout=20)
            v["url"] = resp.url
        except Exception as e:
            print(e)

    return videos


def post_video_to_posterity(video: dict, theatre="all") -> bool:
    data = {
        "url": video["url"],
        "title": video["title"].capitalize(),
        "source": "fredspipa",
        "token": "1234abcd",
        "theatre": theatre,
        "download_now": False
    }
    r = requests.post("https://posterity.no/api/v1/core/post_link", json=data, timeout=60)
    # r = requests.post("http://posterity.test:5050/api/v1/core/post_link", json=data, verify=False)
    if r.status_code == 202 or r.status_code == 200:
        print("Link posted!")
        print(r.text)
        sleep(1)
        return True
    elif r.status_code > 400:
        print(r.text)
    else:
        print(r.text)
        print(f"Unknown response: {r.status_code}")

    sleep(1)
    return False


def clean_up_text(data: str) -> str:
    return strip_useless(remove_emoji(remove_links(remove_tags(data))))


# def paraphrase_text(s: str) -> str:
#     results = parrot.augment(s, use_gpu=False, do_diverse=True, max_length=256, fluency_threshold=0.75, adequacy_threshold=0.75)
#     if not results or not len(results):
#         return s
#
#     if isinstance(results, str):
#         return results
#     elif isinstance(results, list) and len(results):
#         biggest = ""
#         biggest_score = 0
#         for txt, score in results:
#             if score > biggest_score:
#                 biggest = txt
#                 biggest_score = score
#         return biggest if biggest else results[0][0]
#
#     return s

    # return biggest if biggest else results[0][0]


def parse_twitter_list_for_links(twl: str, limit: int = 1000) -> list:
    pass


def clean_up_media_dir():
    from app.serve.db import Video, session_scope
    from app.dl import media_path

    from os import listdir, remove
    from os.path import isfile, join, exists

    original_path = media_path
    processed_path = join(media_path, "processed")
    json_path = media_path

    video_files = [f for f in listdir(original_path) if isfile(join(original_path, f)) and f.endswith(".mp4")]
    processed_files = [f for f in listdir(processed_path) if isfile(join(processed_path, f)) and f.endswith(".mp4")]
    json_files = [f for f in listdir(json_path) if isfile(join(json_path, f)) and f.endswith(".json")]

    video_to_delete = []
    processed_to_delete = []
    json_to_delete = []
    with session_scope() as db_session:
        for vf in video_files:
            video = db_session.query(Video).filter_by(video_id=vf.split(".mp4")[0]).first()
            if video:
                continue
            video_to_delete.append(vf)
        for vf in processed_files:
            video = db_session.query(Video).filter_by(video_id=vf.split(".mp4")[0]).filter_by(post_processed=True).first()
            if video:
                continue
            processed_to_delete.append(vf)
        for jf in json_files:
            video = db_session.query(Video).filter_by(video_id=jf.split(".json")[0]).first()
            if video:
                continue
            json_to_delete.append(jf)

    if not any([len(video_to_delete), len(processed_to_delete), len(json_to_delete)]):
        print("No files to delete.")
        return

    while True:
        total = f"{len(video_to_delete)} originals, {len(processed_to_delete)} processed, {len(json_to_delete)} json to delete. Confirm?"
        confirm = input(f'{total}\n[y]Yes or [n]No or [l]List files: ')
        if confirm == "y":
            break
        elif confirm == "n":
            return  # cancel
        elif confirm == "l":
            for o in video_to_delete:
                print(join(original_path, o))
            for p in processed_to_delete:
                print(join(processed_path, p))
            for j in json_to_delete:
                print(join(json_path, j))
        else:
            print("\n Invalid Option. Please Enter a Valid Option.")

    deleted = 0
    try:
        for j in json_to_delete:
            p = join(json_path, j)
            if exists(p):
                remove(p)
                deleted += 1
        for v in video_to_delete:
            p = join(original_path, v)
            if exists(p):
                remove(p)
                deleted += 1
        for v in processed_to_delete:
            p = join(processed_path, v)
            if exists(p):
                remove(p)
                deleted += 1
    except OSError as e:
        print(e)

    print(f"Deleted {deleted} files.")


if __name__ == "__main__":
    print("Parsing subreddits...")

    all_videos = {
        "ukraine_war": [],
        "yemeni_civil_war": [],
        "palestine": [],
        "kurdish-turkish_conflict": []
    }
    videos = all_videos.copy()

    all_videos["ukraine_war"] += parse_subreddit_for_links("ukraine", limit=100)
    all_videos["ukraine_war"] += parse_subreddit_for_links("UkraineWarVideoReport", limit=100)
    all_videos["yemeni_civil_war"] += parse_subreddit_for_links("YemenVoice", limit=50)
    all_videos["palestine"] += parse_subreddit_for_links("IsraelCrimes", limit=50)
    all_videos["palestine"] += parse_subreddit_for_links("Palestine", limit=50)
    all_videos["kurdish–turkish_conflict"] = parse_subreddit_for_links("kurdistan", limit=50)

    print("Resolving URLs")

    for stub, video_list in all_videos.items():
        print(f"Resolving urls for '{stub}'")
        all_videos[stub] = resolve_urls(video_list)

    print("Checking if links are posted...")
    for stub, video_list in all_videos.items():
        videos[stub] = remove_posted_videos(video_list)

    print("Cleaning up results...")
    for k, v in videos.items():
        videos[k] = clean_up_api_results(v)

    print("Done cleaning, posting links...")
    print("==========================")

    failed = []
    for stub, video_list in videos.items():
        for v in video_list:
            print("-------------------------")
            print(f"Posting {v['title']}")
            success = post_video_to_posterity(v, theatre=stub)
            if not success:
                failed.append(v)

    print("________________________")
    print("FAILED:")
    for f in failed:
        print("======")
        print(f["title"])
        print(f["url"])
        print("======")


    # from app.serve.db import session_scope, Video, Theatre, ContentTag
    # from sqlalchemy import not_
    # from app.serve.search import index_video_data
    # stub = "ukraine_war"
    # with session_scope() as session:
    #     theatre = session.query(Theatre).filter_by(stub=stub).first()
    #     ignore_category = session.query(ContentTag).filter_by(stub="world_news").first()
    #     if theatre and ignore_category:
    #         for v in session.query(Video).filter(not_(Video.tags.any(id=ignore_category.id))).all():
    #             v.theatres = [theatre]
    #             session.add(v)
    #             index_video_data(v)
    #     session.commit()

    # from app.dl.metadata import get_upload_time_from_api
    # with session_scope() as session:
    #     videos = session.query(Video).all()
    #     print("Starting upload time scraping.")
    #     for v in videos:
    #         print(f"Scraping video {v.video_id}")
    #         d = get_upload_time_from_api(v.url)
    #         if d < v.upload_time:
    #             print(f"Updating video {v.video_id}")
    #             v.orig_upload_time = d
    #             session.add(v)
    #     session.commit()

    #
    # metadata = {
    #     "title": "",
    #     "desc": "",
    #     "upload_time": datetime.now()
    # }
    #
    # u = urlparse(url)
    # headers = {
    #     'Accept-Encoding': 'identity',
    #     'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.75 Safari/537.36',
    # }
    # if u.netloc in API_SITES:
    #
    #     if API_SITES[u.netloc] == "twitter":
    #         try:
    #             tweet_id = int(u.path.split("/")[-1])
    #         except (ValueError, IndexError, TypeError):
    #             tweet_id = 0
    #
    #         token = os.environ.get("TWITTER_BEARER_TOKEN", "")
    #         if not len(token) or not tweet_id:
    #             return metadata
    #
    #         headers["Authorization"] = f"Bearer {token}"
    #         req_url = f"https://api.twitter.com/2/tweets/{tweet_id}?tweet.fields=text,created_at"
    #         try:
    #             r = requests.get(req_url, headers=headers)
    #         except Exception as e:
    #             print(e)
    #             print("Error during API request, returning blank")
    #             return metadata
    #
    #         data = r.json()
    #         try:
    #             tweet = data["data"]["text"]
    #         except KeyError as e:
    #             tweet = ""
    #         try:
    #             d = data["data"]["created_at"]
    #             metadata["upload_time"] = parser.parse(d).replace(tzinfo=None)
    #         except (KeyError, ParserError) as e:
    #             metadata["upload_time"] = datetime.now()
    #
    #         metadata["desc"] = remove_links(tweet).lstrip().rstrip().strip("\t")[:1024]
    #         metadata["title"] = remove_emoji(remove_links(tweet.split("\n")[0]))[:256].lstrip().rstrip().strip("\t")
    #
    #     elif API_SITES[u.netloc] == "reddit":
    #         try:
    #             page = reddit.submission(url=url)
    #             if page:
    #                 d = page.created_utc
    #                 metadata["upload_time"] = datetime.utcfromtimestamp(d)
    #                 metadata["desc"] = remove_links(page.selftext)
    #                 metadata["title"] = remove_emoji(page.title)
    #         except Exception as e:
    #             log.error(e)
    #
    # return metadata

