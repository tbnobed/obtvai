"""Build a prompt-based highlight reel: cut the pre-selected clip windows
(chosen by the API via semantic search) from their source assets, encode them
uniformly, and concatenate into a single MP4."""
import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from app import celery_app
from db import get_session
from tasks.proxy import _run_ffmpeg_with_progress, _ENCODERS
from tasks.render import _build_srt, _subtitles_filter
from config import REELS_DIR


def _update_reel(db, reel_id: str, **kwargs):
    from sqlalchemy import text
    set_parts = ", ".join(f"{k} = :{k}" for k in kwargs)
    db.execute(
        text(f"UPDATE reel_jobs SET {set_parts} WHERE id = :rid"),
        {**kwargs, "rid": reel_id},
    )
    db.commit()


def _source_path(db, media_id: str) -> str | None:
    from sqlalchemy import text
    row = db.execute(
        text("SELECT original_path, proxy_path FROM media_assets WHERE id = :mid"),
        {"mid": media_id},
    ).fetchone()
    if not row:
        return None
    original_path, proxy_path = row
    # Prefer the proxy: already H.264/AAC and much faster to cut.
    if proxy_path and os.path.exists(proxy_path):
        return proxy_path
    if original_path and os.path.exists(original_path):
        return original_path
    return None


@celery_app.task(bind=True, name="tasks.reel.build_reel", queue="cpu")
def build_reel(self, reel_id: str):
    db = get_session()
    try:
        from sqlalchemy import text
        row = db.execute(
            text("SELECT clips, preset, burn_captions FROM reel_jobs WHERE id = :rid"),
            {"rid": reel_id},
        ).fetchone()
        if not row:
            raise RuntimeError(f"Reel job {reel_id} not found")
        clips, preset, burn_captions = row
        if isinstance(clips, str):
            clips = json.loads(clips)
        if not clips:
            raise RuntimeError("Reel has no clips to cut")

        _update_reel(db, reel_id, status="running", progress=0.0, error_message=None)

        vertical = preset == "vertical"
        base_filters = (
            ["crop=ih*9/16:ih:(iw-ih*9/16)/2:0", "scale=1080:1920"]
            if vertical
            else ["scale=trunc(iw/2)*2:trunc(ih/2)*2"]
        )

        os.makedirs(REELS_DIR, exist_ok=True)
        tmp_dir = tempfile.mkdtemp(prefix=f"promptreel_{reel_id}_")
        try:
            clip_paths = []
            pinned_encoder = None
            n = len(clips)
            for i, clip in enumerate(clips):
                media_id = clip["media_id"]
                start = float(clip["start_time"])
                end = float(clip["end_time"])
                clip_dur = end - start
                if clip_dur <= 0.5:
                    continue
                src = _source_path(db, media_id)
                if not src:
                    raise RuntimeError(f"No source file available for {clip.get('filename', media_id)}")

                filters = list(base_filters)
                srt_path = None
                if burn_captions:
                    srt_path = os.path.join(tmp_dir, f"cap_{i:02d}.srt")
                    if _build_srt(db, media_id, start, end, srt_path):
                        filters.append(_subtitles_filter(srt_path, vertical))
                    else:
                        srt_path = None

                clip_path = os.path.join(tmp_dir, f"clip_{i:02d}.mp4")
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
                        "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2",
                        "-vf", ",".join(filters + ["fps=30"]),
                        "-movflags", "+faststart",
                        "-progress", "pipe:1", "-nostats",
                        clip_path,
                    ]
                    rc, tail = _run_ffmpeg_with_progress(cmd, 0, lambda pct: None, timeout=900)
                    if rc == 0:
                        pinned_encoder = (label, codec_args)
                        break
                if rc != 0:
                    raise RuntimeError(f"ffmpeg failed cutting clip {i + 1}: {tail[-400:]}")
                clip_paths.append(clip_path)
                _update_reel(db, reel_id, progress=round((i + 1) / n * 90.0, 1))

            if not clip_paths:
                raise RuntimeError("No usable clips could be cut")

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
            result = subprocess.run(concat_cmd, capture_output=True, text=True, timeout=600)
            if result.returncode != 0:
                raise RuntimeError(f"ffmpeg concat failed: {result.stderr[-400:]}")

            final_path = os.path.join(REELS_DIR, f"reel_{reel_id}.mp4")
            shutil.move(reel_tmp, final_path)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        _update_reel(
            db, reel_id,
            status="success", progress=100.0,
            output_path=final_path, finished_at=datetime.utcnow(),
        )

    except Exception as e:
        db.rollback()
        try:
            _update_reel(
                db, reel_id,
                status="error", error_message=str(e)[:2000],
                finished_at=datetime.utcnow(),
            )
        except Exception:
            db.rollback()
        raise
    finally:
        db.close()
