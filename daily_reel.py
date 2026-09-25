"""Local, read-only source scanning and one-second-per-day monthly rendering."""
from __future__ import annotations

import argparse
import calendar
import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps, ImageCms

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pillow_heif = None

VERSION = "1.1.0"
BASE = Path(__file__).resolve().parent
PHOTO = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".tif", ".tiff", ".webp"}
VIDEO = {".mp4", ".mov", ".m4v", ".avi", ".mts", ".m2ts", ".mkv", ".3gp"}
RAW = {".arw", ".cr2", ".cr3", ".nef", ".dng", ".raf", ".orf", ".rw2"}
FIELDS = ["day", "kind", "source", "path", "capture_local", "start_seconds", "date_source", "warnings"]


def emit(message):
    print(message, flush=True)


def run(args, **kw):
    p = subprocess.run([str(x) for x in args], stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, **kw)
    if p.returncode:
        raise RuntimeError(p.stderr.decode("utf-8", "replace")[-4000:])
    return p.stdout


def tool(name):
    ext = ".exe" if os.name == "nt" else ""
    local = BASE / "bin" / (name + ext)
    found = str(local) if local.exists() else shutil.which(name)
    if not found:
        raise RuntimeError(f"{name} was not found. See README.md; put it in bin or on PATH.")
    return found


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def write_csv(path, rows, fields=FIELDS):
    with Path(path).open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def read_rows(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def months_between(first, last):
    a = datetime.strptime(first, "%Y-%m").date().replace(day=1)
    b = datetime.strptime(last, "%Y-%m").date().replace(day=1)
    if a > b:
        raise ValueError("Start month must be on or before end month.")
    while a <= b:
        yield a.strftime("%Y-%m")
        a = (a.replace(day=28) + timedelta(days=4)).replace(day=1)


def month_days(month):
    y, m = map(int, month.split("-"))
    return [date(y, m, d).isoformat() for d in range(1, calendar.monthrange(y, m)[1] + 1)]


def beneath(path, root):
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


def load_config(path):
    cfg = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    list(months_between(cfg["start_month"], cfg["end_month"]))
    cfg.setdefault("priority", "video-first")
    cfg.setdefault("width", 1920)
    cfg.setdefault("height", 1080)
    cfg.setdefault("fps", 30)
    cfg.setdefault("audio", True)
    cfg.setdefault("photo_zoom", 0.04)
    cfg.setdefault("crf", 18)
    if cfg["priority"] not in {"video-first", "mobile-first"}:
        raise ValueError("priority must be video-first or mobile-first")
    if cfg["fps"] != 30 or any(int(cfg[k]) <= 0 or int(cfg[k]) % 2 for k in ["width", "height"]):
        raise ValueError("Use 30 fps and positive, even frame dimensions.")
    if not 0 <= float(cfg["photo_zoom"]) <= 0.15:
        raise ValueError("photo_zoom must be between 0 and 0.15.")
    if not cfg.get("sources"):
        raise ValueError("Choose at least one media folder.")
    roots = []
    for source in cfg["sources"]:
        if source["type"] not in {"mobile", "camera"}:
            raise ValueError("Source type must be mobile or camera.")
        source.setdefault("timezone", "America/Chicago")
        source.setdefault("video_clock", "utc" if source["type"] == "mobile" else "local")
        if source["video_clock"] not in {"utc", "local"}:
            raise ValueError("video_clock must be utc or local.")
        ZoneInfo(source["timezone"])
        root = Path(source["path"]).expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"Source folder is unavailable: {root}")
        if any(beneath(root, other) or beneath(other, root) for other in roots):
            raise ValueError("Source folders overlap. Select each archive branch only once.")
        source["path"] = str(root)
        roots.append(root)
    out = Path(cfg["output"]).expanduser().resolve()
    if any(beneath(out, root) or beneath(root, out) for root in roots):
        raise ValueError("Choose a separate output folder outside the source trees.")
    cfg["output"] = str(out)
    out.mkdir(parents=True, exist_ok=True)
    return cfg


def parse_time(value):
    if not value:
        return None
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    s = str(value).strip().strip("\x00")
    s = re.sub(r"^(\d{4}):(\d{2}):(\d{2})", r"\1-\2-\3", s)
    s = s.replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(s)
        return d if 1970 <= d.year <= 2100 else None
    except ValueError:
        return None


def filename_date(path):
    # Only full year/month/day dates. Never use filesystem creation/modification times.
    name = Path(path).stem
    pattern = r"(?<!\d)((?:19|20)\d{2})[-_]?([01]\d)[-_]?([0-3]\d)(?:[T _-]([0-2]\d)[.:_-]?([0-5]\d)[.:_-]?([0-5]\d))?(?!\d)"
    for match in re.finditer(pattern, name):
        y, m, d, hh, mm, ss = match.groups()
        try:
            dt = datetime(int(y), int(m), int(d), int(hh or 0), int(mm or 0), int(ss or 0))
            return dt.isoformat() if hh else dt.date().isoformat(), "filename", "Filename-derived date; review it."
        except ValueError:
            continue
    # A full date in one parent component is safe to propose; year/month alone is not.
    for part in reversed(Path(path).parts[:-1]):
        if re.fullmatch(r"(?:19|20)\d{2}[-_]\d{2}[-_]\d{2}", part):
            try:
                return date.fromisoformat(part.replace("_", "-")).isoformat(), "folder", "Folder-derived date; time unknown."
            except ValueError:
                pass
    return "", "unknown", "No trustworthy capture date. Assign a date manually in selection.csv."


def photo_date(path):
    with Image.open(path) as image:
        exif = image.getexif()
        tags = dict(exif)
        try:
            tags.update(exif.get_ifd(34665))
        except (KeyError, TypeError, ValueError):
            pass
        for key, offset, label in [(36867, 36881, "EXIF DateTimeOriginal"),
                                   (36868, 36882, "EXIF DateTimeDigitized")]:
            dt = parse_time(tags.get(key))
            if dt:
                off = tags.get(offset)
                if off and dt.tzinfo is None:
                    dt = parse_time(dt.isoformat() + str(off)) or dt
                return dt.isoformat(), label, "" if key == 36867 else "Digitized time used; review for scans/edits."
    return filename_date(path)


def probe(path):
    return json.loads(run([tool("ffprobe"), "-v", "error", "-show_format", "-show_streams",
                           "-of", "json", path], timeout=120))


def video_stream(info):
    return next((s for s in info["streams"] if s.get("codec_type") == "video"
                 and not s.get("disposition", {}).get("attached_pic")), None)


def video_date(info, source, path):
    tags = {k.lower(): v for s in info.get("streams", []) for k, v in s.get("tags", {}).items()}
    tags.update({k.lower(): v for k, v in info.get("format", {}).get("tags", {}).items()})
    for key in ["com.apple.quicktime.creationdate", "creationdate", "date_time_original", "datetimeoriginal"]:
        dt = parse_time(tags.get(key))
        if dt:
            # Keep the actual local offset embedded at capture, including travel.
            return dt.isoformat(), key, "" if dt.tzinfo else "Local capture clock; offset not embedded."
    dt = parse_time(tags.get("creation_time"))
    if dt:
        if source["video_clock"] == "utc":
            dt = dt.replace(tzinfo=dt.tzinfo or timezone.utc).astimezone(ZoneInfo(source["timezone"]))
            warning = "Container UTC converted using source timezone; review travel dates."
        else:
            dt = dt.replace(tzinfo=None)
            warning = "Container clock treated as camera local time; verify the camera clock setting."
        return dt.isoformat(), "container creation_time", warning
    return filename_date(path)


def describe(path, source):
    kind = "photo" if path.suffix.lower() in PHOTO else "video"
    result = {"path": str(path), "source": source["type"], "kind": kind, "duration": 0}
    if kind == "photo":
        captured, origin, warning = photo_date(path)
    else:
        info = probe(path)
        stream = video_stream(info)
        if not stream:
            raise ValueError("No decodable video stream.")
        duration = float(stream.get("duration") or info.get("format", {}).get("duration") or 0)
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("Unknown or invalid video duration.")
        result.update(duration=duration, video_index=stream["index"],
                      audio=any(s.get("codec_type") == "audio" for s in info["streams"]),
                      transfer=stream.get("color_transfer", "unknown"),
                      primaries=stream.get("color_primaries", "unknown"))
        captured, origin, warning = video_date(info, source, path)
        from screen_recording import detect
        result['screen_recording_reason'] = detect(path, info)
        if result['screen_recording_reason']:
            warning = (warning + ' | ' + result['screen_recording_reason']).strip(' |')
    result.update(capture_local=captured, day=captured[:10], date_source=origin, warnings=warning)
    return result


def scan(cfg):
    out = Path(cfg["output"])
    db = sqlite3.connect(out / "metadata-cache.sqlite")
    db.execute("CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, payload TEXT)")
    records, problems = [], []
    count, cached = 0, 0
    def walk_error(error):
        # An inaccessible tree must not silently turn a month into missing-day cards.
        raise RuntimeError(f"Cannot scan folder: {error}")
    try:
        for source in cfg["sources"]:
            emit(f"Scanning {source['type']}: {source['path']}")
            for folder, dirs, names in os.walk(source["path"], onerror=walk_error):
                dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in {"$RECYCLE.BIN", "System Volume Information"})
                for name in sorted(names):
                    path = Path(folder) / name
                    ext = path.suffix.lower()
                    if ext in RAW:
                        problems.append({"path": str(path), "reason": "RAW requires a JPEG/TIFF export first; original is untouched."})
                        continue
                    if ext not in PHOTO | VIDEO:
                        continue
                    count += 1
                    try:
                        stat = path.stat()
                        key = hashlib.sha256(json.dumps([VERSION, str(path), stat.st_size, stat.st_mtime_ns, source], sort_keys=True).encode()).hexdigest()
                        hit = db.execute("SELECT payload FROM cache WHERE key=?", (key,)).fetchone()
                        if hit:
                            record = json.loads(hit[0])
                            cached += 1
                        else:
                            record = describe(path, source)
                            db.execute("INSERT OR REPLACE INTO cache VALUES (?,?)", (key, json.dumps(record)))
                        if record["day"] and cfg["start_month"] <= record["day"][:7] <= cfg["end_month"]:
                            records.append(record)
                        elif not record["day"]:
                            problems.append({"path": str(path), "reason": record["warnings"]})
                    except Exception as error:
                        problems.append({"path": str(path), "reason": str(error)[:800]})
                    if count % 100 == 0:
                        db.commit()
                        emit(f"{count:,} media files examined; {cached:,} from cache.")
        db.commit()
    finally:
        db.close()
    write_json(out / "catalog.json", {"version": VERSION, "config": cfg, "records": records})
    write_csv(out / "needs-attention.csv", problems, ["path", "reason"])
    emit(f"Scan finished: {count:,} examined; {len(records):,} dated candidates in range; {len(problems):,} need attention.")
    return records


def rank(record, cfg):
    source_rank = int(record["source"] != "mobile")
    kind_rank = int(record["kind"] != "video")
    first = (kind_rank, source_rank) if cfg["priority"] == "video-first" else (source_rank, kind_rank)
    return first + (record["capture_local"], record["path"].casefold())


def default_start(record):
    if record["kind"] != "video":
        return 0.0
    value = max(0.0, (record["duration"] - 1) / 2)
    captured = parse_time(record["capture_local"])
    if captured and len(record["capture_local"]) > 10:
        day_end = captured.replace(hour=23, minute=59, second=59, microsecond=0)
        value = min(value, max(0.0, (day_end - captured).total_seconds()))
    return round(value, 3)


def row_from(record):
    return {key: record.get(key, "") for key in FIELDS} | {"start_seconds": default_start(record)}


def blank_row(day):
    return dict.fromkeys(FIELDS, "") | {"day": day, "kind": "missing", "start_seconds": 0,
                                       "warnings": "No dated candidate selected. Check needs-attention.csv too."}


def load_catalog(cfg):
    catalog = json.loads((Path(cfg["output"]) / "catalog.json").read_text(encoding="utf-8"))
    for key in ["sources", "start_month", "end_month"]:
        if catalog["config"].get(key) != cfg.get(key):
            raise ValueError("Folders, dates, or clock settings changed. Scan again before reviewing or rendering.")
    return catalog["records"]


def make_plan(cfg, records=None, reset=False):
    out = Path(cfg["output"])
    records = records if records is not None else load_catalog(cfg)
    grouped = {}
    for record in records:
        if record["kind"] == "video" and record["duration"] <= 1:
            continue
        grouped.setdefault(record["day"], []).append(record)
    plan_path = out / "selection.csv"
    existing = {r["day"]: r for r in read_rows(plan_path)} if plan_path.exists() and not reset else {}
    rows = []
    for month in months_between(cfg["start_month"], cfg["end_month"]):
        for day in month_days(month):
            from screen_recording import prefer_non_screen
            candidates = sorted(prefer_non_screen(grouped.get(day, [])), key=lambda r: rank(r, cfg))
            rows.append(existing.get(day) or (row_from(candidates[0]) if candidates else blank_row(day)))
    if plan_path.exists():
        shutil.copy2(plan_path, out / "selection.previous.csv")
    write_csv(plan_path, rows)
    write_csv(out / "candidates.csv", [row_from(r) for r in sorted(records, key=lambda r: (r["day"], rank(r, cfg)))])
    emit(f"Plan ready: {len(rows)} days; {sum(r['kind']=='missing' for r in rows)} placeholders; {sum(bool(r['warnings']) for r in rows)} rows with notes.")
    if existing:
        emit("Existing day choices preserved. Reset defaults only when you want to discard them.")
    return rows


def timestamp_text(row):
    if row["kind"] == "missing":
        return datetime.fromisoformat(row["day"]).strftime("%b %d, %Y") + "  |  No media selected"
    captured = row["capture_local"]
    if len(captured) == 10:
        return date.fromisoformat(captured).strftime("%b %d, %Y") + "  |  Time unknown"
    dt = parse_time(captured)
    if row["kind"] == "video":
        dt += timedelta(seconds=float(row["start_seconds"]))
    return dt.strftime("%b %d, %Y  |  %I:%M:%S %p")


def font(size):
    choices = [Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "segoeui.ttf",
               Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
               Path("/System/Library/Fonts/Supplemental/Arial.ttf")]
    for path in choices:
        if path.exists():
            return ImageFont.truetype(str(path), size)
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def caption_layer(text, width, height):
    layer = Image.new("RGBA", (width, height))
    draw = ImageDraw.Draw(layer)
    size = max(12, round(height * 0.031))
    typeface = font(size)
    while draw.textlength(text, font=typeface) > width * 0.91 and size > 10:
        size -= 1
        typeface = font(size)
    pad = max(6, round(height * 0.012))
    bounds = draw.textbbox((0, 0), text, font=typeface)
    tw, th = bounds[2] - bounds[0], bounds[3] - bounds[1]
    x, y = (width - tw) / 2, height - max(12, height * 0.036) - th
    draw.rounded_rectangle((x-pad, y-pad, x+tw+pad, y+th+pad), radius=pad, fill=(0, 0, 0, 176))
    draw.text((x-bounds[0], y-bounds[1]), text, font=typeface, fill="white")
    return layer


def open_photo(path):
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source)
        icc = source.info.get("icc_profile")
        if icc:
            try:
                image = ImageCms.profileToProfile(image, ImageCms.ImageCmsProfile(io.BytesIO(icc)),
                                                 ImageCms.createProfile("sRGB"), outputMode="RGB")
            except (ImageCms.PyCMSError, ValueError, OSError):
                image = image.convert("RGB")
        return image.convert("RGB").copy()


def photo_frames(row, cfg):
    w, h, fps = cfg["width"], cfg["height"], cfg["fps"]
    caption = caption_layer(timestamp_text(row), w, h)
    if row["kind"] == "missing":
        image = Image.new("RGB", (w, h), (17, 23, 32))
        d = ImageDraw.Draw(image)
        title = "A day between memories"
        f = font(round(h * .044))
        d.text((w/2, h/2), title, font=f, fill=(188, 200, 208), anchor="mm")
        image.paste(caption, mask=caption)
        for _ in range(fps):
            yield image
        return
    original = open_photo(row["path"])
    small = ImageOps.fit(original, (max(2, w//4), max(2, h//4)), method=Image.Resampling.LANCZOS)
    background = small.filter(ImageFilter.GaussianBlur(max(4, h/70))).resize((w, h))
    background = Image.blend(background, Image.new("RGB", (w, h), "black"), .24)
    zoom = float(cfg["photo_zoom"])
    base_scale = min(w/original.width, h/original.height) / (1 + zoom)
    # The foreground stays entirely visible, even at maximum zoom.
    for frame in range(fps):
        t = frame / max(1, fps - 1)
        scale = base_scale * (1 + zoom * (3*t*t - 2*t*t*t))
        size = (max(1, round(original.width*scale)), max(1, round(original.height*scale)))
        foreground = original.resize(size, Image.Resampling.LANCZOS)
        image = background.copy()
        image.paste(foreground, ((w-size[0])//2, (h-size[1])//2))
        image.paste(caption, mask=caption)
        yield image


def encoding(cfg):
    return ["-c:v", "libx264", "-preset", "medium", "-crf", str(cfg["crf"]),
            "-pix_fmt", "yuv420p", "-color_primaries", "bt709", "-color_trc", "bt709",
            "-colorspace", "bt709", "-color_range", "tv", "-threads", "2",
            "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", "-t", "1"]


def render_still(row, cfg, target):
    w, h, fps = cfg["width"], cfg["height"], cfg["fps"]
    args = [tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", "-filter_threads", "1",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(fps), "-i", "pipe:0",
            "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-map", "0:v:0", "-map", "1:a:0",
            "-vf", "scale=in_range=full:out_range=tv:out_color_matrix=bt709,setsar=1",
            *encoding(cfg), str(target)]
    with tempfile.TemporaryFile() as error:
        proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=error)
        try:
            for frame in photo_frames(row, cfg):
                proc.stdin.write(frame.tobytes())
            proc.stdin.close()
            code = proc.wait(timeout=600)
            if code:
                error.seek(0)
                raise RuntimeError(error.read().decode("utf-8", "replace")[-4000:])
        except Exception:
            proc.kill()
            proc.wait()
            error.seek(0)
            detail = error.read().decode("utf-8", "replace")[-4000:]
            if detail:
                emit(detail)
            raise


def render_video(row, cfg, target, info):
    stream = video_stream(info)
    w, h, fps = cfg["width"], cfg["height"], cfg["fps"]
    has_audio = cfg["audio"] and any(s.get("codec_type") == "audio" for s in info["streams"])
    transfer = stream.get("color_transfer")
    color = ""
    if transfer in {"smpte2084", "arib-std-b67"}:
        color = "zscale=t=linear:npl=100,format=gbrpf32le,tonemap=tonemap=hable:desat=0,zscale=p=bt709:t=bt709:m=bt709:r=limited,"
    elif stream.get("color_primaries") == "bt2020":
        raise ValueError("Wide-gamut video has no supported HDR transfer tag. Export an SDR copy for this day.")
    else:
        color = "scale=out_color_matrix=bt709:out_range=tv,"
    with tempfile.TemporaryDirectory(prefix="daily-reel-") as work:
        caption_layer(timestamp_text(row), w, h).save(Path(work) / "caption.png")
        args = [tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", "-filter_complex_threads", "1",
                "-ss", str(float(row["start_seconds"])), "-i", row["path"],
                "-loop", "1", "-framerate", str(fps), "-i", "caption.png"]
        if not has_audio:
            args += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
        audio = "0:a:0" if has_audio else "2:a:0"
        filters = (
            f"[0:{stream['index']}]setpts=PTS-STARTPTS,{color}fps={fps},"
            f"tpad=stop_mode=clone:stop_duration=1,trim=end_frame={fps},setpts=N/({fps}*TB),"
            "scale=w=trunc(iw*sar/2)*2:h=ih,setsar=1,split=2[bg][fg];"
            f"[bg]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
            "boxblur=20:2[blur];"
            f"[fg]scale={w}:{h}:force_original_aspect_ratio=decrease:force_divisible_by=2[fit];"
            "[blur][fit]overlay=(W-w)/2:(H-h)/2:shortest=1[scene];"
            "[scene][1:v]overlay=0:0:shortest=1,setsar=1,format=yuv420p[v];"
            f"[{audio}]asetpts=PTS-STARTPTS,aresample=48000,"
            "aformat=sample_fmts=s16:channel_layouts=stereo,apad=whole_len=48000,"
            "atrim=end_sample=48000,afade=t=in:d=0.01,afade=t=out:st=0.99:d=0.01,asetpts=N/SR/TB[a]"
        )
        args += ["-filter_complex", filters, "-map", "[v]", "-map", "[a]", *encoding(cfg), str(target)]
        run(args, cwd=work, timeout=600)


def validate_row(row, cfg, known):
    if row["kind"] == "missing":
        return None
    if row["kind"] not in {"photo", "video"}:
        raise ValueError("kind must be photo, video, or missing")
    path = Path(row["path"])
    if not path.is_file() or not any(beneath(path, s["path"]) for s in cfg["sources"]):
        raise ValueError(f"Source missing or outside selected folders: {path}")
    captured = parse_time(row["capture_local"])
    if not captured or captured.date().isoformat() != row["day"]:
        raise ValueError("capture_local must contain the selected day and a real capture date.")
    original = known.get(str(path))
    if row["date_source"] != "manual":
        if not original or row["capture_local"] != original["capture_local"]:
            raise ValueError("Changed file/date: select it in Review, or set date_source to manual after verifying the date.")
    start = float(row["start_seconds"] or 0)
    if not math.isfinite(start) or start < 0:
        raise ValueError("start_seconds must be a finite, nonnegative number.")
    if row["kind"] == "photo":
        if start:
            raise ValueError("Photo start_seconds must be zero.")
        return None
    info = probe(path)
    stream = video_stream(info)
    if not stream:
        raise ValueError("No video stream.")
    duration = float(stream.get("duration") or info["format"].get("duration") or 0)
    if duration <= 1:
        raise ValueError("Videos of one second or less are excluded; choose a photo for this date.")
    if not math.isfinite(duration) or duration <= 0 or start >= duration:
        raise ValueError(f"Start {start}s is outside the video (duration {duration}s).")
    if len(row["capture_local"]) > 10 and (captured + timedelta(seconds=start)).date() != captured.date():
        raise ValueError("Selected excerpt begins on a different day; choose an earlier start.")
    return info


def doctor():
    ff = tool("ffmpeg")
    tool("ffprobe")
    filters = run([ff, "-hide_banner", "-filters"]).decode("utf-8", "replace")
    required = ["overlay", "boxblur", "fps", "tpad", "zscale", "tonemap", "scale"]
    missing = [name for name in required if not re.search(r"\s"+name+r"\s", filters)]
    if missing:
        raise RuntimeError("FFmpeg is missing filters: " + ", ".join(missing) + ". Install a full FFmpeg build.")
    encoders = run([ff, "-hide_banner", "-encoders"]).decode("utf-8", "replace")
    if "libx264" not in encoders:
        raise RuntimeError("FFmpeg must include the libx264 encoder.")
    ZoneInfo("America/Chicago")
    emit("FFmpeg, FFprobe, H.264, tone mapping, and timezone support are ready.")
    emit("HEIC/HEIF support: " + ("ready" if pillow_heif else "not installed; run Setup.cmd for iPhone photos."))


def check_video(path, expected_frames):
    data = json.loads(run([tool("ffprobe"), "-v", "error", "-count_frames", "-select_streams", "v:0",
                           "-show_entries", "stream=nb_read_frames,duration", "-show_entries", "format=duration",
                           "-of", "json", path], timeout=600))
    frames = int(data["streams"][0]["nb_read_frames"])
    duration = float(data["format"]["duration"])
    if frames != expected_frames or abs(duration - expected_frames/30) > .055:
        raise RuntimeError(f"Output verification failed: {frames} frames, {duration:.4f}s.")


def render(cfg, month=None):
    doctor()
    out = Path(cfg["output"])
    records = load_catalog(cfg)
    known = {r["path"]: r for r in records}
    all_rows = read_rows(out / "selection.csv")
    months = list(months_between(cfg["start_month"], cfg["end_month"]))
    if month and month not in months:
        raise ValueError("Requested month is outside the configured range.")
    for current in [month] if month else months:
        rows = [r for r in all_rows if r["day"][:7] == current]
        rows.sort(key=lambda r: r["day"])
        if [r["day"] for r in rows] != month_days(current):
            raise ValueError(f"{current}: selection.csv must have exactly one row per calendar day.")
        cache = out / ".segments"
        cache.mkdir(exist_ok=True)
        segments = []
        for row in rows:
            emit(f"{row['day']}  {row['kind']}  {Path(row['path']).name if row['path'] else ''}")
            try:
                info = validate_row(row, cfg, known)
                stat = Path(row["path"]).stat() if row["kind"] != "missing" else None
                fingerprint = [VERSION, row, {k: cfg[k] for k in ["width", "height", "fps", "audio", "photo_zoom", "crf"]},
                               (stat.st_size, stat.st_mtime_ns) if stat else None]
                key = hashlib.sha256(json.dumps(fingerprint, sort_keys=True).encode()).hexdigest()[:24]
                target = cache / (key + ".mkv")
                marker = cache / (key + ".ok")
                if not target.exists() or not marker.exists():
                    temp = cache / (key + ".partial.mkv")
                    if row["kind"] == "video":
                        render_video(row, cfg, temp, info)
                    else:
                        render_still(row, cfg, temp)
                    check_video(temp, cfg["fps"])
                    temp.replace(target)
                    marker.write_text(VERSION, encoding="ascii")
                segments.append(target)
            except Exception as error:
                raise RuntimeError(f"{row['day']}: {error}\nChange this day's selection and render again; finished segments are cached.") from error
        month_key = hashlib.sha256("".join(p.name for p in segments).encode()).hexdigest()
        target_dir = out / current[:4]
        target_dir.mkdir(exist_ok=True)
        destination = target_dir / f"{current}.mp4"
        signature = destination.with_suffix(".signature")
        if destination.exists() and signature.exists() and signature.read_text() == month_key:
            emit(f"Unchanged: {destination}")
            continue
        # Concat paths are controlled hexadecimal cache names, never user-supplied filter text.
        concat_file = cache / "concat.txt"
        concat_file.write_text("".join(f"file '{p.name}'\nduration 1.0\n" for p in segments), encoding="ascii")
        partial = target_dir / (current + ".partial.mp4")
        run([tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "1",
             "-i", concat_file, "-map", "0:v:0", "-map", "0:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
             "-ar", "48000", "-ac", "2", "-t", str(len(rows)), "-movflags", "+faststart", partial], timeout=600)
        check_video(partial, len(rows)*cfg["fps"])
        if destination.exists():
            prior = destination.with_name(current + ".previous-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".mp4")
            destination.replace(prior)
        partial.replace(destination)
        signature.write_text(month_key, encoding="ascii")
        write_csv(target_dir / f"{current}-selections.csv", rows)
        emit(f"READY: {destination}  ({len(rows)} seconds, {len(rows)*cfg['fps']} frames)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["doctor", "scan", "plan", "scan-plan", "highlights", "render"])
    parser.add_argument("--config", default=str(BASE / "config.json"))
    parser.add_argument("--month", help="Render only YYYY-MM; default all configured months")
    parser.add_argument("--reset", action="store_true", help="Rebuild default selections, backing up the previous CSV")
    args = parser.parse_args()
    if args.command == "doctor":
        doctor()
        return
    cfg = load_config(args.config)
    if args.command == "scan":
        scan(cfg)
    elif args.command == "scan-plan":
        make_plan(cfg, scan(cfg), args.reset)
    elif args.command == "plan":
        make_plan(cfg, reset=args.reset)
    elif args.command == "render":
        render(cfg, args.month)
    elif args.command == "highlights":
        import highlights
        highlights.main(cfg)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        emit(f"ERROR: {error}")
        sys.exit(1)

