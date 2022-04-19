import os
import praw
import dotenv
dotenv.load_dotenv()
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


def parse_subreddit_for_links(sr: str, limit: int = 1000) -> list:
    subreddit = reddit.subreddit(sr)
    videos = {}
    for submission in subreddit.new(limit=10):
        if submission.is_video:
            print(submission.title)

    pass


def paraphrase_text(s: str) -> str:
    from transformers import PegasusTokenizerFast, PegasusForConditionalGeneration
    model = PegasusForConditionalGeneration.from_pretrained("tuner007/pegasus_paraphrase")
    tokenizer = PegasusTokenizerFast.from_pretrained("tuner007/pegasus_paraphrase")

    sentences = get_paraphrased_sentences(model, tokenizer, s)
    return sentences


def get_paraphrased_sentences(model, tokenizer, sentence, num_return_sequences=1, num_beams=10):
    # tokenize the text to be form of a list of token IDs
    inputs = tokenizer([sentence], truncation=True, padding="longest", return_tensors="pt")
    # generate the paraphrased sentences
    outputs = model.generate(
        **inputs,
        num_beams=num_beams,
        num_return_sequences=num_return_sequences,
    )
    # decode the generated sentences using the tokenizer to get them back to text
    return tokenizer.batch_decode(outputs, skip_special_tokens=True)


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
    # parse_subreddit_for_links("ukraine")
    txt = paraphrase_text("RU propagandist Andrey Rudenko posted a video of alleged vote in Rozovsky district of Zaporizhzhya region during which «inhabitants chose to join the DPR». RU occupants now do not even bother staging fake referendums—fake votes in what looks like a school hall suffice")
    print(txt)
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