# one-sec-day

Create monthly memory videos from your own photos and videos: one second for every calendar day, with a capture date and time at the bottom. A 31-day month produces a 31-second movie.

Python handles local scanning, metadata, selection, and the Windows interface. FFmpeg trims and renders video. No AI models, cloud processing, or media uploads are used.

## Features

- Mobile-first selection: mobile video, mobile photo, camera video, camera photo. Optional video-first mode prefers camera video over a mobile photo.
- Videos of one second or less are excluded from automatic selection and rendering.
- Optional Auto highlights samples interior excerpts and ranks sharpness, exposure, and motion. It checks up to five videos spread across each day's capture times and three excerpts per video, rather than analyzing every second.
- Highlight sampling avoids two seconds at each end when the video is long enough. Shorter videos use proportional margins.
- Likely screen recordings are flagged using filenames and metadata. When the same day and source have another eligible unflagged video, flagged clips are excluded before highlight sampling. Otherwise they remain available with a review warning.
- Photos use an eased 4% zoom. Portrait media fits over a blurred background.
- Bottom captions use capture metadata and include the selected video's excerpt offset. Unknown times are labeled rather than invented.
- Missing days receive one-second dated cards, preserving calendar length.
- Output: 1920x1080 SDR H.264/AAC MP4, 30 fps, with original video audio and silent photos/cards.
- Manual day-by-day review, metadata caching, reusable rendered segments, and CSV selection records.

## Windows setup

1. Clone or download this repository into a local folder:

   ```powershell
   git clone https://github.com/seshasaisrivatsav/one-sec-day.git
   cd one-sec-day
   ```

2. Install Python 3.11 or newer with the Python launcher and Tcl/Tk support.
3. Install a full FFmpeg build. Put **ffmpeg.exe and ffprobe.exe** in `bin/`, or add their containing directory to PATH. It must provide libx264, zscale, and tonemap. See `bin/PUT-FFMPEG-HERE.txt`.
4. Double-click `Setup.cmd`. It creates `.venv`, installs the Python dependencies, and checks FFmpeg. This setup step requires internet access.
5. Double-click `Start.cmd` to open the app.

FFmpeg binaries, Python environments, and third-party packages are not bundled. Once dependencies are installed, scanning and rendering operate locally.

## Generate your first month

1. Add your phone folder(s) and camera folder(s). Select month or year folders to limit the scan. Subfolders are scanned recursively.
2. Choose a separate output folder outside all source folders. Source roots must not overlap.
3. Set the start and end to the same month, for example `2026-01`.
4. Choose `mobile-first` and verify the fallback timezone.
5. Click **Save & scan**. Inspect `needs-attention.csv` in the output folder for unreadable or undated files.
6. Click **Auto highlights** if you want quality-based selection and screen-recording filtering. It replaces current choices and backs up the previous selection CSV. Without this step, new automatic choices use the earliest file in the winning priority tier and its middle second.
7. Click **Review days**, inspect the originals, and change any file or excerpt start. Save selections before rendering.
8. Enter the desired month beside the render button and click **Render this month**.

The movie is saved under `<output>/2026/2026-01.mp4`, alongside `2026-01-selections.csv`. Watch it to check the memories, timestamps, color, and framing.

## Generate other months or years

Add the relevant year folders for mobile and camera media, then set a range such as `2025-01` through `2025-12`. Run **Save & scan**, optionally **Auto highlights**, review the selections, and choose **Render all configured months**. Each month gets its own MP4 under a year folder.

You can add multiple source folders, including archives on different drives. Do not add both a parent folder and its child. Scanning retains existing day choices; Auto highlights rebuilds them. Only run one job against an output folder at a time. The current month includes cards for future days, so use the last completed month when appropriate.

## Command-line usage

Copy `config.example.json` to `config.json`, replace the placeholder paths, and choose months. `config.json` is local and ignored by Git.

From PowerShell in the repository folder:

```powershell
.\.venv\Scripts\python.exe daily_reel.py doctor
.\.venv\Scripts\python.exe daily_reel.py scan-plan
.\.venv\Scripts\python.exe daily_reel.py highlights
.\.venv\Scripts\python.exe daily_reel.py render --month 2026-01
```

Render all configured months:

```powershell
.\.venv\Scripts\python.exe daily_reel.py render
```

Rebuild the earliest-file defaults, replacing previous selections:

```powershell
.\.venv\Scripts\python.exe daily_reel.py plan --reset
```

Use `--config path/to/config.json` with any configuration-dependent command to select another configuration. Advanced options include per-source timezone and video clock interpretation, frame dimensions, photo zoom, audio, and CRF. Keep `fps` at 30. Higher resolutions require more render time and disk space.

## Date and time rules

- Photos prefer EXIF DateTimeOriginal, then DateTimeDigitized.
- Videos prefer embedded local capture timestamps, preserving their explicit timezone offset.
- Generic container creation time defaults to UTC converted into the source timezone for mobile media, or the recorded local clock for camera media.
- A full date/time in the filename or a full date in a parent folder is a fallback. Year/month folders alone cannot establish the day.
- Filesystem creation/modification dates are never treated as capture dates.
- Check travel footage and camera clock settings. Filename times can differ from embedded metadata; embedded capture metadata takes precedence.
- For separate travel folders, configure the appropriate source timezone without also including their parent. Changing the GUI fallback timezone updates source timezone settings.

For a verified manual date correction, close Review and edit `selection.csv`. Keep exactly one row per day. Supply `kind`, `source`, full `path`, `capture_local`, `start_seconds`, and `date_source=manual`. The capture date must match the row's day. Use a date-only value when the time is unknown. `capture_local` is the recording start; the caption adds `start_seconds` itself.

## Limits and review

Screen-recording detection is a heuristic, not proof. Renamed or stripped recordings may escape detection, while cropped/exported camera footage may be flagged. The screen flag does not override source priority. Review can manually select a flagged recording.

Quality scoring does not recognize people, events, or emotional significance. It may prefer scenery, objects, or a less meaningful moment. Manual review remains useful.

Supported photos include JPEG, PNG, HEIC/HEIF, TIFF, and WebP. Supported video containers include MP4, MOV, M4V, AVI, MTS, M2TS, MKV, and 3GP; decoding depends on FFmpeg. RAW photos are reported for export to JPEG/TIFF first. Tagged PQ/HLG has basic SDR tone mapping; Dolby Vision, camera log, and unusual metadata need visual checking. Only a recording's capture-start day is indexed, even if it spans midnight.

Output folders contain local source paths and timestamps in CSV/catalog files. Keep these private when sharing a movie. Git ignores local configuration, media, output folders, caches, and environments. Originals are read only.

## Tests and validation

```powershell
.\.venv\Scripts\python.exe -m unittest discover -v
```

Nine tests cover dates, priorities, timezone handling, short-video photo fallback, screen-recording heuristics, and a complete synthetic month with output-cache reuse. Tests require FFmpeg. A real January 2026 pilot was rendered on Windows and verified as 31 seconds, 930 frames, 1920x1080 with audio. Example media is not included. Interactive GUI operation and all possible media formats have not been exhaustively tested.

## Project files

| File | Purpose |
| --- | --- |
| `app.py` | Windows GUI for configuration, review, and rendering |
| `daily_reel.py` | Metadata scanner, calendar planner, renderer, CLI |
| `highlights.py` | Non-AI excerpt sampling and quality scoring |
| `screen_recording.py` | Screen-recording heuristics and alternative preference |
| `config.example.json` | Portable configuration template |
| `Setup.cmd` / `Start.cmd` | Windows setup and launch |
| `test_*.py` | Automated tests |
