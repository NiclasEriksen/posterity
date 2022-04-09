


def parse_ffmpeg_output(line: str) -> (int, int, float):
    frame = 0
    fps = 0
    time = 0.0
    if "frame" in line and "fps" in line and "time" in line:
        pass
    else:
        return frame, fps, time

    line_segments = []
    for seg in line.split("="):
        for s in seg.split(" "):
            if len(s):
                line_segments.append(s.strip())

    try:
        s = line_segments
        d = {s[i]: s[i+1] for i in range(0, len(s) - 1, 2)}
    except IndexError:
        print(f"Invalid ffmpeg line? {len(s)} items")
        return frame, fps, time

    if "frame" in d.keys():
        try:
            frame = int(d["frame"])
        except (TypeError, ValueError):
            frame = 0
    if "fps" in d.keys():
        try:
            fps = int(d["fps"])
        except (TypeError, ValueError):
            fps = 0
    if "time" in d.keys():
        try:
            hrs, mins, sec = d["time"].split(":")
        except ValueError:  # not enough/too many
            hrs, mins, sec = "00", "00", "00.00"
        try:
            hrs, mins, sec = int(hrs), int(mins), float(sec)
        except (TypeError, ValueError):
            hrs, mins, sec = 0, 0, 0.0

        time = (hrs * 3600) + (mins * 60) + sec

    return frame, fps, time


def get_last_time(log_path, max_search=100) -> float:
    try:
        i = 0
        for l in reverse_readline(log_file):
            if l.startswith("out_time="):
                ts = l.split("out_time=")[1].strip()
                try:
                    hrs, mins, sec = ts.split(":")
                except ValueError:  # not enough/too many
                    hrs, mins, sec = "00", "00", "00.00"
                try:
                    hrs, mins, sec = int(hrs), int(mins), float(sec)
                except (TypeError, ValueError):
                    hrs, mins, sec = 0, 0, 0.0

                time = (hrs * 3600) + (mins * 60) + sec
                return time

            i += 1
            if i >= max_search:
                return 0
    except OSError:
        return 0


if __name__ == "__main__":
    from app.dl.dl import add_technical_info_to_all, refresh_json_on_all
    # add_technical_info_to_all()
    # refresh_json_on_all()
    import subprocess
    pass


    # open(log_file, "w").close()
    # input_fps = 25
    # input_duration = 67.0
    #
    # line = "frame= 2377 fps= 33 q=39.4 Lsize=   36693kB time=00:00:39.87 bitrate=7538.8kbits/s speed=0.553x "
    #
    # cmd = [
    #     "ffmpeg", "-i", input_file, "-v", "34", "-y",
    #     "-progress", log_file,
    #     "-f", "mp4", output_file,
    # ]
    # process = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

