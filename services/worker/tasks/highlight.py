"""Build a highlight reel by cutting clips at AI-detected key moments and
concatenating them into a single MP4."""
import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from app import celery_app
from db import get_session
from tasks.base import update_job, append_log, update_asset
from tasks.proxy import _run_ffmpeg_with_progress, _ENCODERS
from tasks.render import _build_srt, _subtitles_filter
from config import REELS_DIR

# Seconds of video captured for each key moment.
CLIP_SECONDS = 8.0
# Start each clip slightly before the moment so the lead-in isn't clipped.
LEAD_IN_SECONDS = 1.0
MAX_CLIPS = 8
# Pace bounds the length of each key-moment clip window.
PACE_SECONDS = {"fast": 6.0, "normal": 8.0, "cinematic": 15.0}


def _select_windows(moments: list, duration: float,
                    max_clips: int = MAX_CLIPS,
                    clip_seconds: float = CLIP_SECONDS) -> list[tuple[float, float]]:
    """Turn key moments into non-overlapping (start, end) clip windows."""
    times = []
    for m in moments:
        try:
            t = float(m.get("time")) if isinstance(m, dict) else float(m)
        except (TypeError, ValueError):
            continue
        if t < 0:
            continue
        if duration > 0 and t >= duration:
            continue
        times.append(t)
    times.sort()

    windows: list[tuple[float, float]] = []
    for t in times[: max_clips * 2]:
        start = max(0.0, t - LEAD_IN_SECONDS)
        end = start + clip_seconds
        if duration > 0:
            end = min(end, duration)
        if end - start < 2.0:
            continue
        if windows and start < windows[-1][1]:
            # Overlaps previous clip: extend it instead of duplicating footage.
            prev_start, prev_end = windows[-1]
            windows[-1] = (prev_start, max(prev_end, end))
            continue
        windows.append((start, end))
        if len(windows) >= max_clips:
            break
    return windows


@celery_app.task(bind=True, name="tasks.highlight.build_highlight", queue="cpu")
def build_highlight(self, media_id: str, job_id: str, clips: list = None,
                    preset: str = "original", burn_captions: bool = False,
                    max_clips: int = MAX_CLIPS, pace: str = "normal"):
    db = get_session()
    try:
        update_job(db, job_id, status="running", started_at=datetime.utcnow(),
                   celery_task_id=self.request.id, progress=0.0)
        append_log(db, job_id, "Building highlight reel")

        from sqlalchemy import text
        row = db.execute(
            text("""
                SELECT original_path, proxy_path, duration_seconds, key_moments
                FROM media_assets WHERE id = :mid
            """),
            {"mid": media_id},
        ).fetchone()
        if not row:
            raise RuntimeError(f"Media asset {media_id} not found")

        original_path, proxy_path, duration_val, key_moments = row
        duration = float(duration_val) if duration_val else 0.0
        if isinstance(key_moments, str):
            key_moments = json.loads(key_moments)
        if not key_moments:
            raise RuntimeError("No key moments available — run AI analysis first")

        # Prefer the proxy: already H.264/AAC and much faster to cut.
        src = proxy_path if proxy_path and os.path.exists(proxy_path) else original_path
        if not src or not os.path.exists(src):
            raise RuntimeError("No source file available for clipping")

        # User-curated clip list from the preview wins over recomputing —
        # the render must match exactly what the user approved.
        if clips:
            windows = []
            for c in clips:
                try:
                    s = max(0.0, float(c["start_time"]))
                    e = float(c["end_time"])
                except (KeyError, TypeError, ValueError):
                    raise RuntimeError(f"Malformed curated clip: {c!r}")
                if duration > 0:
                    e = min(e, duration)
                if e - s < 0.5:
                    raise RuntimeError(f"Curated clip too short after clamping: {s}-{e}")
                windows.append((s, e))
            append_log(db, job_id, f"Using {len(windows)} user-curated clip(s) from preview")
        else:
            windows = _select_windows(
                key_moments, duration,
                max_clips=max(1, min(int(max_clips or MAX_CLIPS), 20)),
                clip_seconds=PACE_SECONDS.get(pace, CLIP_SECONDS),
            )
        if not windows:
            raise RuntimeError("Key moments did not yield any usable clip windows")

        vertical = preset == "vertical"
        base_filters = (
            ["crop=ih*9/16:ih:(iw-ih*9/16)/2:0", "scale=1080:1920"]
            if vertical
            else ["scale=trunc(iw/2)*2:trunc(ih/2)*2"]
        )
        append_log(
            db, job_id,
            f"Cutting {len(windows)} clips from {os.path.basename(src)}"
            f" (preset={preset}, captions={'on' if burn_captions else 'off'})",
        )

        os.makedirs(REELS_DIR, exist_ok=True)
        tmp_dir = tempfile.mkdtemp(prefix=f"reel_{media_id}_")
        try:
            clip_paths = []
            pinned_encoder = None
            n = len(windows)
            for i, (start, end) in enumerate(windows):
                clip_path = os.path.join(tmp_dir, f"clip_{i:02d}.mp4")
                clip_dur = end - start

                filters = list(base_filters)
                if burn_captions:
                    srt_path = os.path.join(tmp_dir, f"cap_{i:02d}.srt")
                    if _build_srt(db, media_id, start, end, srt_path):
                        filters.append(_subtitles_filter(srt_path, vertical))

                rc, tail = -1, ""
                # Pin the encoder after the first successful clip so every
                # segment shares identical codec settings — required for the
                # lossless concat (-c copy) below.
                encoders = [pinned_encoder] if pinned_encoder else list(_ENCODERS)
                for label, codec_args in encoders:
                    cmd = [
                        "ffmpeg", "-y",
                        "-ss", f"{start:.2f}", "-i", src, "-t", f"{clip_dur:.2f}",
                        *codec_args,
                        "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
                        "-vf", ",".join(filters + ["fps=30"]),
                        "-movflags", "+faststart",
                        "-progress", "pipe:1", "-nostats",
                        clip_path,
                    ]
                    rc, tail = _run_ffmpeg_with_progress(cmd, 0, lambda pct: None, timeout=600)
                    if rc == 0:
                        pinned_encoder = (label, codec_args)
                        break
                    append_log(db, job_id, f"Clip {i + 1} {label} failed (exit {rc}): {tail[:200]}")
                if rc != 0:
                    raise RuntimeError(f"ffmpeg failed cutting clip {i + 1}: {tail}")
                clip_paths.append(clip_path)
                update_job(db, job_id, progress=round((i + 1) / n * 90.0, 1))
                append_log(db, job_id, f"Clip {i + 1}/{n} done ({start:.1f}s → {end:.1f}s)")

            # All clips share codec/resolution/fps, so concat without re-encoding.
            list_path = os.path.join(tmp_dir, "concat.txt")
            with open(list_path, "w") as f:
                for p in clip_paths:
                    f.write(f"file '{p}'\n")
            reel_tmp = os.path.join(tmp_dir, "reel.mp4")
            concat_cmd = [
                "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path,
                "-c", "copy", "-movflags", "+faststart", reel_tmp,
            ]
            result = subprocess.run(concat_cmd, capture_output=True, text=True, timeout=300)
            if result.returncode != 0:
                raise RuntimeError(f"ffmpeg concat failed: {result.stderr[-400:]}")

            final_path = os.path.join(REELS_DIR, f"{media_id}.mp4")
            shutil.move(reel_tmp, final_path)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        update_asset(db, media_id, highlight_url=f"{media_id}.mp4")
        update_job(db, job_id, status="success", finished_at=datetime.utcnow(), progress=100.0)
        append_log(db, job_id, f"Highlight reel ready: {len(windows)} clips")

    except Exception as e:
        db.rollback()
        update_job(db, job_id, status="error", error_message=str(e), finished_at=datetime.utcnow())
        raise
    finally:
        db.close()
