"""Deterministic, local quality sampling; no learned models or external services."""
import json
from pathlib import Path
import numpy as np
import daily_reel as r
from screen_recording import detect, prefer_non_screen

def starts(record):
    duration = record['duration']
    margin = min(2.0, (duration - 1) / 4)
    low, high = margin, duration - 1 - margin
    captured = r.parse_time(record['capture_local'])
    if captured and len(record['capture_local']) > 10:
        high = min(high, (captured.replace(hour=23, minute=59, second=59) - captured).total_seconds())
    if high < low:
        return [max(0, high)]
    return sorted(set(round(float(v), 3) for v in np.linspace(low, high, 3)))

def quality(path, start):
    raw = r.run([r.tool('ffmpeg'), '-v', 'error', '-ss', str(start), '-i', path,
                 '-t', '1', '-vf', 'fps=8,scale=160:90:force_original_aspect_ratio=decrease,pad=160:90:(ow-iw)/2:(oh-ih)/2',
                 '-an', '-pix_fmt', 'gray', '-f', 'rawvideo', '-threads', '1', 'pipe:1'], timeout=90)
    frames = np.frombuffer(raw, np.uint8).reshape(-1, 90, 160).astype(np.float32)
    if len(frames) < 6:
        raise ValueError('Too few decoded frames')
    # Ignore borders to reduce influence from portrait padding.
    frames = frames[:, 10:80, 60:100]
    lap = -4*frames[:,1:-1,1:-1]+frames[:,:-2,1:-1]+frames[:,2:,1:-1]+frames[:,1:-1,:-2]+frames[:,1:-1,2:]
    sharp = float(np.median(np.var(lap, axis=(1,2))))
    clipped = float(np.mean((frames < 12) | (frames > 243)))
    motion = np.mean(np.abs(np.diff(frames, axis=0)), axis=(1,2))
    # Reward detail and moderate change; penalize clipping and abrupt motion.
    score = np.log1p(sharp) - 3*clipped + .025*min(float(np.mean(motion)), 12) - .055*max(0,float(np.max(motion))-18)
    return float(score)

def main(cfg=None, days=None):
    cfg = cfg or r.load_config(r.BASE/'config.json')
    records = r.load_catalog(cfg)
    # Old catalogs do not contain the screen metadata. Enrich them once, before
    # sampling, so flagged videos cannot crowd alternatives out of the five slots.
    for rec in records:
        if rec['kind'] == 'video' and 'screen_recording_reason' not in rec and (days is None or rec['day'] in days):
            rec['screen_recording_reason'] = detect(rec['path'], r.probe(rec['path']))
            if rec['screen_recording_reason']:
                rec['warnings'] = (rec.get('warnings', '') + ' | ' + rec['screen_recording_reason']).strip(' |')
    catalog_path = Path(cfg['output'])/'catalog.json'
    catalog = json.loads(catalog_path.read_text(encoding='utf-8'))
    catalog['records'] = records
    r.write_json(catalog_path, catalog)
    if days is None:
        rows = r.make_plan(cfg, records, reset=True)
    else:
        rows = r.read_rows(Path(cfg['output'])/'selection.csv')
        r.write_csv(Path(cfg['output'])/'selection.before-screen-filter.csv', rows)
    audit = []
    for row in rows:
        if row['kind'] != 'video' or (days is not None and row['day'] not in days):
            continue
        candidates = sorted([v for v in records if v['day']==row['day'] and v['source']==row['source'] and v['kind']=='video' and v['duration']>1], key=lambda v: (v['capture_local'],v['path']))
        candidates = prefer_non_screen(candidates)
        # Bound pilot runtime and cover the day's capture times evenly.
        indexes = sorted(set(int(x) for x in np.linspace(0,len(candidates)-1,min(5,len(candidates)))))
        best = None
        for index in indexes:
            rec = candidates[index]
            for start in starts(rec):
                entry = dict(day=row['day'],path=rec['path'],start_seconds=start)
                try:
                    score = quality(rec['path'],start)
                    entry['score'] = score
                    if best is None or score > best[0]:
                        best = score,rec,start
                except Exception as error:
                    entry['error'] = str(error)
                audit.append(entry)
        if best:
            row.update(r.row_from(best[1]))
            row['start_seconds'] = best[2]
        else:
            raise RuntimeError('No decodable highlight for '+row['day'])
        r.emit(f"Highlight {row['day']}: {Path(row['path']).name} at {row['start_seconds']}s")
        r.write_json(Path(cfg['output'])/'highlight-audit.json',audit)
    r.write_csv(Path(cfg['output'])/'selection.csv',rows)

if __name__ == '__main__':
    main()
