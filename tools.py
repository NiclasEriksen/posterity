
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
    from app.serve.db import session_scope, Video, Theatre, ContentTag
    from sqlalchemy import not_
    from app.serve.search import index_video_data
    stub = "ukraine_war"
    with session_scope() as session:
        theatre = session.query(Theatre).filter_by(stub=stub).first()
        ignore_category = session.query(ContentTag).filter_by(name="World News").first()
        if theatre and ignore_category:
            for v in session.query(Video).filter(not_(Video.tags.any(id=ignore_category.id))).all():
                v.theatres = [theatre]
                session.add(v)
                index_video_data(v)
        session.commit()

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
