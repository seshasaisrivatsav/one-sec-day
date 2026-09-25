"""Editor projects and deterministic selection, independent of the GUI."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import daily_reel as reel
import highlights
from screen_recording import prefer_non_screen

RESOLUTIONS = {'1080p': (1920, 1080), '2K (1440p)': (2560, 1440), '4K': (3840, 2160)}


def save(path, project):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(project, indent=2), encoding='utf-8')
    temp.replace(path)


def fresh():
    return dict(version=1, sources=[], records=[], selections={}, locked=[], priority='mobile', month='', issues=[])


def load(path):
    project = json.loads(Path(path).read_text(encoding='utf-8'))
    if project.get('version') != 1:
        raise ValueError('Unsupported editor project version')
    for key in fresh():
        if key not in project:
            raise ValueError('Incomplete project: '+key)
    return project


def media_key(record):
    path = Path(record['path'])
    stat = path.stat()
    return hashlib.sha256(f'{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}'.encode()).hexdigest()


def scan(sources, cache_dir, progress=lambda text: None):
    """Scan every selected folder recursively, retaining undated files too."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir/'metadata.json'
    cache = json.loads(cache_file.read_text(encoding='utf-8')) if cache_file.exists() else {}
    records, issues, seen = [], [], set()
    for source in sources:
        if not Path(source['path']).is_dir():
            raise ValueError('Source folder unavailable: '+source['path'])
        def walk_error(error):
            raise OSError(f'Cannot read source folder: {error}')
        for folder, dirs, names in os.walk(source['path'], onerror=walk_error):
            dirs[:] = sorted(d for d in dirs if not d.startswith('.') and d not in {'$RECYCLE.BIN','System Volume Information'})
            for name in sorted(names):
                path = Path(folder)/name
                normalized = str(path.resolve()).casefold()
                if normalized in seen:
                    continue
                seen.add(normalized)
                if path.suffix.lower() in reel.RAW:
                    issues.append(dict(path=str(path), reason='RAW: export a JPEG or TIFF first.'))
                    continue
                if path.suffix.lower() not in reel.PHOTO | reel.VIDEO:
                    continue
                progress(f'Reading {len(records)+1}: {name}')
                try:
                    key = media_key({'path':str(path)}) + json.dumps(source,sort_keys=True)
                    rec = copy.deepcopy(cache.get(key))
                    if rec is None:
                        rec = reel.describe(path, source)
                        if rec['kind'] == 'video':
                            stream = reel.video_stream(reel.probe(path))
                            rec['width'],rec['height'] = stream.get('width',0),stream.get('height',0)
                        else:
                            with reel.open_photo(path) as photo:
                                rec['width'],rec['height'] = photo.size
                        cache[key] = rec
                    records.append(rec)
                except Exception as error:
                    issues.append(dict(path=str(path),reason=str(error)))
    save(cache_file,cache)
    return sorted(records,key=lambda r:(r['capture_local'],r['path'])),issues


def months(project):
    return sorted({r['day'][:7] for r in project['records'] if r['day']} | ({project['month']} if project['month'] else set()))


def rows(project, month):
    return [project['selections'].get(day,reel.blank_row(day)) for day in reel.month_days(month)]


def automatic(project, month, cache_dir, progress=lambda text: None):
    """All eligible videos are scored; manual choices survive reruns."""
    result = copy.deepcopy(project)
    cache_file = Path(cache_dir)/'scores.json'
    scores = json.loads(cache_file.read_text(encoding='utf-8')) if cache_file.exists() else {}
    for day in reel.month_days(month):
        if day in result['locked']:
            continue
        candidates = [r for r in result['records'] if r['day']==day and (r['kind']=='photo' or r['duration']>1)]
        videos = [r for r in candidates if r['kind']=='video']
        candidates = prefer_non_screen(videos) + [r for r in candidates if r['kind']=='photo']
        def tier(rec):
            return (rec['kind']!='video',rec['source']!=result['priority'])
        candidates.sort(key=lambda rec:(tier(rec),rec['capture_local'],rec['path']))
        best = None
        for index, rec in enumerate(candidates):
            if best and tier(rec)>tier(best[1]):
                break
            progress(f'{day}: scoring {index+1}/{len(candidates)} — {Path(rec["path"]).name}')
            for start in highlights.starts(rec) if rec['kind']=='video' else [0]:
                try:
                    key = media_key(rec)+f'|{start}|editor-v1'
                    if key not in scores:
                        if rec['kind']=='video':
                            score = highlights.quality(rec['path'],start)
                        else:
                            import numpy as np
                            with reel.open_photo(rec['path']) as photo:
                                photo.thumbnail((320,320))
                                a = np.asarray(photo.convert('L'),dtype=float)
                            lap = -4*a[1:-1,1:-1]+a[:-2,1:-1]+a[2:,1:-1]+a[1:-1,:-2]+a[1:-1,2:]
                            score = float(np.log1p(lap.var())-3*np.mean((a<12)|(a>243)))
                        score += .3*math.log1p(rec.get('width',0)*rec.get('height',0)/1_000_000)
                        scores[key] = score
                    if best is None or scores[key]>best[0]:
                        best = scores[key],rec,start
                except Exception as error:
                    result['issues'].append(dict(path=rec['path'],reason=f'Quality sample: {error}'))
        if best:
            row = reel.row_from(best[1]); row['start_seconds'] = best[2]
            result['selections'][day] = row
        else:
            result['selections'][day] = reel.blank_row(day)
        save(cache_file,scores)
    return result


def select(project, record, start=0):
    if not record['day']:
        raise ValueError('Assign a date to this media before using it.')
    if record['kind']=='video' and (record['duration']<=1 or start<0 or start+1>record['duration']+.0001):
        raise ValueError('Choose a full one-second window in a video longer than one second.')
    if record['kind']=='video':
        from datetime import timedelta
        captured = reel.parse_time(record['capture_local'])
        if captured and (captured+timedelta(seconds=start)).date()!=captured.date():
            raise ValueError('This window begins on the next date. Choose an earlier start.')
    row = reel.row_from(record)
    row['start_seconds'] = round(start,3) if record['kind']=='video' else 0
    project['selections'][record['day']] = row
    if record['day'] not in project['locked']:
        project['locked'].append(record['day'])
    return row


def config(project, month, out, size):
    return dict(sources=project['sources'],output=str(out),start_month=month,end_month=month,
                priority='video-first',width=size[0],height=size[1],fps=30,audio=True,photo_zoom=.04,crf=18)


def render_month(project, month, out, size):
    out = Path(out); out.mkdir(parents=True,exist_ok=True)
    cfg = config(project,month,out,size)
    reel.write_json(out/'catalog.json',dict(config=cfg,records=project['records']))
    reel.write_csv(out/'selection.csv',rows(project,month))
    reel.render(cfg,month)
    return str(out/month[:4]/f'{month}.mp4')


def preview(record, start, project, cache_dir):
    row = reel.row_from(record) if record['kind']!='missing' else record.copy()
    row['start_seconds'] = start if record['kind']=='video' else 0
    folder = Path(cache_dir)/'previews'; folder.mkdir(parents=True,exist_ok=True)
    fingerprint = [row,media_key(record) if record['kind']!='missing' else 'blank']
    target = folder/(hashlib.sha256(json.dumps(fingerprint,sort_keys=True).encode()).hexdigest()+'.mp4')
    if not target.exists():
        cfg = config(project,row['day'][:7],folder,(960,540))
        temp = target.with_suffix('.partial.mkv')
        if row['kind']=='video':
            reel.render_video(row,cfg,temp,reel.probe(row['path']))
        else:
            reel.render_still(row,cfg,temp)
        reel.check_video(temp,30)
        reel.run([reel.tool('ffmpeg'),'-v','error','-y','-i',str(temp),'-c:v','copy',
                  '-c:a','aac','-movflags','+faststart',str(target)],timeout=90)
        temp.unlink()
    return str(target)


def thumbnail(record, cache_dir):
    folder = Path(cache_dir)/'thumbnails'; folder.mkdir(parents=True,exist_ok=True)
    target = folder/(media_key(record)+'.jpg')
    if not target.exists():
        if record['kind']=='photo':
            with reel.open_photo(record['path']) as photo:
                photo.thumbnail((192,108)); photo.convert('RGB').save(target)
        else:
            reel.run([reel.tool('ffmpeg'),'-v','error','-ss',str(reel.default_start(record)),
                      '-i',record['path'],'-frames:v','1','-vf','scale=192:108:force_original_aspect_ratio=decrease',
                      '-threads','1','-y',str(target)],timeout=60)
    return str(target)
