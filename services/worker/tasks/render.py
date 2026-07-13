"""Render a clip window to a standalone MP4, with optional 9:16 reversioning
and burned-in captions built from the transcript."""
import os
import subprocess
import tempfile
from datetime import datetime
from app import celery_app
from db import get_session
from tasks.proxy import _run_ffmpeg_with_progress, _ENCODERS
from config import RENDERS_DIR


def _update_render(db, render_id: str, **kwargs):
    from sqlalchemy import text
    set_parts = ", ".join(f"{k} = :{k}" for k in kwargs)
    db.execute(
        text(f"UPDATE render_jobs SET {set_parts} WHERE id = :rid"),
        {**kwargs, "rid": render_id},
    )
    db.commit()


def _srt_timestamp(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds % 1) * 1000))
    if ms >= 1000:
        s, ms = s + 1, ms - 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _build_srt(db, media_id: str, start: float, end: float, path: str) -> bool:
    """Write an SRT of transcript segments overlapping [start, end], with
    timestamps re-based to the clip. Returns False when nothing overlaps."""
    from sqlalchemy import text
    rows = db.execute(
        text("""
            SELECT start_time, end_time, text
            FROM transcript_segments
            WHERE media_id = :mid AND end_time > :start AND start_time < :end
            ORDER BY start_time
        """),
        {"mid": media_id, "start": start, "end": end},
    ).fetchall()
    if not rows:
        return False
    with open(path, "w", encoding="utf-8") as f:
        for i, (seg_start, seg_end, seg_text) in enumerate(rows, 1):
            s = max(0.0, float(seg_start) - start)
            e = min(end - start, float(seg_end) - start)
            if e <= s:
                continue
            f.write(f"{i}\n{_srt_timestamp(s)} --> {_srt_timestamp(e)}\n{(seg_text or '').strip()}\n\n")
    return True


def _subtitles_filter(srt_path: str, vertical: bool) -> str:
    # Escape for ffmpeg filter parsing: backslash, colon, quote.
    escaped = srt_path.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    size = 14 if vertical else 20
    style = (
        f"FontSize={size},PrimaryColour=&H00FFFFFF,OutlineColour=&H80000000,"
        f"BorderStyle=1,Outline=2,Shadow=0,MarginV={40 if vertical else 24}"
    )
    return f"subtitles='{escaped}':force_style='{style}'"


@celery_app.task(bind=True, name="tasks.render.render_clip", queue="cpu")
def render_clip(self, render_id: str):
    db = get_session()
    tmp_srt = None
    try:
        from sqlalchemy import text
        row = db.execute(
            text("""
                SELECT r.media_id, r.start_time, r.end_time, r.preset, r.burn_captions,
                       a.original_path, a.proxy_path
                FROM render_jobs r
                JOIN media_assets a ON a.id = r.media_id
                WHERE r.id = :rid
            """),
            {"rid": render_id},
        ).fetchone()
        if not row:
            raise RuntimeError(f"Render job {render_id} not found")

        media_id, start, end, preset, burn_captions, original_path, proxy_path = row
        start, end = float(start), float(end)
        clip_dur = end - start

        _update_render(db, render_id, status="running", progress=0.0, error_message=None)

        # Prefer the original for quality; the proxy is the fallback.
        src = original_path if original_path and os.path.exists(original_path) else proxy_path
        if not src or not os.path.exists(src):
            raise RuntimeError("No source file available for rendering")

        os.makedirs(RENDERS_DIR, exist_ok=True)
        output_path = os.path.join(RENDERS_DIR, f"{render_id}.mp4")

        filters = ["scale=trunc(iw/2)*2:trunc(ih/2)*2"]
        if preset == "vertical":
            # Center-crop to 9:16 then normalize to 1080x1920.
            filters = ["crop=ih*9/16:ih:(iw-ih*9/16)/2:0", "scale=1080:1920"]

        if burn_captions:
            tmp_srt = tempfile.NamedTemporaryFile(
                mode="w", suffix=".srt", delete=False, prefix=f"cap_{render_id}_"
            ).name
            if _build_srt(db, media_id, start, end, tmp_srt):
                filters.append(_subtitles_filter(tmp_srt, preset == "vertical"))
            else:
                os.unlink(tmp_srt)
                tmp_srt = None

        def report(pct: float):
            _update_render(db, render_id, progress=float(pct))

        rc, tail = -1, ""
        for label, codec_args in _ENCODERS:
            cmd = [
                "ffmpeg", "-y",
                "-ss", f"{start:.3f}", "-i", src, "-t", f"{clip_dur:.3f}",
                *codec_args,
                "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2",
                "-vf", ",".join(filters),
                "-movflags", "+faststart",
                "-progress", "pipe:1", "-nostats",
                output_path,
            ]
            rc, tail = _run_ffmpeg_with_progress(cmd, clip_dur, report, timeout=1800)
            if rc == 0:
                break
        if rc != 0:
            raise RuntimeError(f"ffmpeg render failed: {tail}")

        _update_render(
            db, render_id,
            status="success", progress=100.0,
            output_path=output_path, finished_at=datetime.utcnow(),
        )

    except Exception as e:
        db.rollback()
        try:
            _update_render(
                db, render_id,
                status="error", error_message=str(e)[:2000],
                finished_at=datetime.utcnow(),
            )
        except Exception:
            db.rollback()
        raise
    finally:
        if tmp_srt and os.path.exists(tmp_srt):
            os.unlink(tmp_srt)
        db.close()
