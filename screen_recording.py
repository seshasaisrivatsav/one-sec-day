"""Conservative metadata heuristics, not image recognition or certainty."""
import re
from pathlib import Path

def detect(path, info):
    tags = {str(k).lower(): str(v) for k, v in info.get('format', {}).get('tags', {}).items()}
    stream_tags = [s.get('tags', {}) for s in info.get('streams', [])]
    text = ' '.join([Path(path).stem] + list(tags.values()) +
                    [str(v) for t in stream_tags for v in t.values()])
    if re.search(r'screen[ _-]*(?:record(?:ing|er)?|capture)|replaykit|com\.apple\.replay', text, re.I):
        return 'Explicit screen-recording filename or metadata'
    video = next((s for s in info.get('streams', []) if s.get('codec_type') == 'video'), {})
    width, height = int(video.get('width', 0)), int(video.get('height', 0))
    camera = any(k.endswith(('.make', '.model')) or k in {'make', 'model'} for k in tags)
    core = any('Core Media Video' in str(t.get('handler_name', '')) for t in stream_tags)
    # Typical full phone-display shape plus an Apple export signature, without
    # camera identity. Cropped/exported camera footage can still match this.
    ratio = max(width, height) / min(width, height) if min(width, height) else 0
    if 2.05 <= ratio <= 2.4 and core and tags.get('major_brand', '').strip() == 'mp42' and not camera:
        return f'Likely phone-screen export: {width}x{height}, Core Media/mp42, no camera identity'
    return ''

def prefer_non_screen(records):
    """Preserve source preference; demote suspects only with another same-tier video."""
    clean_sources = {v['source'] for v in records
                     if v['kind'] == 'video' and v.get('duration', 0) > 1
                     and not v.get('screen_recording_reason')}
    return [v for v in records if not (v['kind'] == 'video'
            and v.get('screen_recording_reason') and v['source'] in clean_sources)]
