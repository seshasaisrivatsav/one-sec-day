# One Second Day — Desktop Editor (V1)

Run `editor\Start-Editor.cmd` from this repository on Windows. It uses the repository Python environment and installs PySide6 if needed. FFmpeg and ffprobe must be available (the existing repository setup supplies them).

1. Choose **Import folders**, then **Add folders**. Ctrl-select several folders or add them in several batches. Each is scanned recursively. Label each mobile or camera, check the capture timezone and video clock (mobile defaults UTC), and press OK.
2. Save an `.osd.json` project. The editor imports dated and undated media and automatically selects the first available month. Use the month menu to change months, then **Auto-select month**. Add month allows an empty calendar month too.
3. The left pane groups each day into horizontally scrolling videos and photos. Mouse wheel scrolls a media row horizontally; use the outer scrollbar for other days. Green items with a check mark are used in the timeline. Undated files appear under Uncategorised.
4. Click any video to inspect it. Drag the blue fixed one-second window or enter an exact start time. **Play 1 second** renders an accurate preview including audio and the timestamp. **Use for this day** replaces that day's selection and locks your manual choice. Unlock a timeline day to allow automatic replacement.
5. Click a timeline day, then **Play timeline from selected day**. A cached 540p preview is rendered first, including eased photo zoom, timestamps, and missing-day cards. Use Play / Pause during playback.
6. **Export month** offers 1920×1080, 2560×1440 (2K), or 3840×2160 (4K). Movies and selection CSVs are written below the chosen folder as `resolution\year\YYYY-MM.mp4`. Existing exports are retained with a previous timestamp before replacement.

Drag the horizontal and vertical dividers to resize the panels. The initial upper/lower split is approximately 70/30. Projects autosave after edits and preserve all monthly selections, manual locks, imported sources, and dates. Open project resumes editing. Original media is never renamed or modified.

## Selection rules

Eligible videos always precede photos. Videos of one second or less are excluded. Screen recordings are avoided when another eligible video exists. Mobile priority / Camera priority chooses the preferred source within that media type; it falls back when that source has no eligible media. Automatic reselection preserves manually locked days.

Every video in the preferred eligible group is sampled at three interior one-second windows. The score uses sharpness, exposure, frame-change penalties as a rough steadiness estimate, and resolution. It avoids the shutter edges where duration allows; very short videos necessarily have smaller margins. This is a heuristic, not a judgement of emotional significance. V1 does not detect people. Local, offline people detection is planned for V2.

Capture metadata is preferred, followed by timestamped filenames and supported date folders. Undated media is retained; select it and assign a verified capture date before using it. A missing date uses a dated template card. Unsupported RAW files and unreadable files appear in the issues dialog.

## Development

`python -m pip install -r editor/requirements.txt`

`python -m unittest discover -s editor -p "test_*.py"`

The editor uses [Qt for Python](https://doc.qt.io/qtforpython-6/) for native windows and playback, and the repository renderer for exports. Editor state, metadata, thumbnails, and render caches live under ignored `runtime/editor-cache`; save private project JSON under `runtime` or outside the repo. Preview generation and scoring run in background threads. The existing CLI runners are unchanged.

Current limitations: initial full-library scanning/scoring and full-month preview generation can take time; source playback depends on Qt's installed codecs, while rendered previews use H.264. A source preview shows the raw file; Play 1 second shows the final treatment. No cancellation of an in-progress render in V1. Do not import a folder containing the editor's own exports.
