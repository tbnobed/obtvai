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
    set_parts = ", ".join(
        f"{k} = CAST(:{k} AS jsonb)" if k == "clips" else f"{k} = :{k}"
        for k in kwargs
    )
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


_CURATE_MIN_CLIP = 4.0
_CURATE_MAX_CLIP = 45.0
_CONTEXT_PAD = 25.0


def _curate_clips(
    db, prompt: str, candidates: list[dict],
    target_duration: float | None = None,
) -> list[dict] | None:
    """Story-editor pass over the API's semantic-search candidates.

    Shows the LLM each candidate with surrounding transcript context and asks
    it to trim to complete thoughts, cut weak moments, and order for narrative
    flow. Returns refined clips, or None to keep the raw candidates.
    """
    from sqlalchemy import text
    from tasks.analyze import (
        _load_llm, _generate, _extract_json,
        _format_timecode, _timecode_to_seconds, CREATIVE_PERSONA, EDITOR_RULES,
    )
    from tasks.visual_context import clip_visual_profile, describe_profile

    blocks = []
    windows = []  # (media_id, filename, ctx_start, ctx_end)
    for i, c in enumerate(candidates):
        mid = c["media_id"]
        ctx_s = max(0.0, float(c["start_time"]) - _CONTEXT_PAD)
        ctx_e = float(c["end_time"]) + _CONTEXT_PAD
        rows = db.execute(
            text("""
                SELECT start_time, end_time, text FROM transcript_segments
                WHERE media_id = :mid AND end_time >= :s AND start_time <= :e
                ORDER BY start_time
            """),
            {"mid": mid, "s": ctx_s, "e": ctx_e},
        ).fetchall()
        if not rows:
            continue
        lines = "\n".join(
            f"  [{_format_timecode(float(r[0]))}-{_format_timecode(float(r[1]))}] {r[2]}"
            for r in rows
        )
        visual = describe_profile(
            clip_visual_profile(db, mid, float(c["start_time"]), float(c["end_time"]))
        )
        blocks.append(
            f"CANDIDATE {i} — file: {c['filename']} "
            f"(flagged moment {_format_timecode(float(c['start_time']))}-"
            f"{_format_timecode(float(c['end_time']))}):\n"
            f"  VISUALS: {visual}\n{lines}"
        )
        windows.append((mid, c["filename"], float(rows[0][0]), float(rows[-1][1])))
        if len("\n\n".join(blocks)) > 14000:
            break

    if not blocks:
        return None

    # Duration-aware clip length cap: long-form targets allow longer clips.
    max_clip = _CURATE_MAX_CLIP
    if target_duration:
        max_clip = max(_CURATE_MAX_CLIP, min(300.0, target_duration / max(len(candidates), 1) * 1.5))

    tokenizer, model = _load_llm()
    llm_prompt = (
        f"You are a senior video editor cutting a highlight reel. {CREATIVE_PERSONA}\n"
        f"{EDITOR_RULES}\n"
        f'Editorial brief: "{prompt}"\n\n'
        "Below are candidate moments found by search, each with surrounding "
        "transcript context and timecodes.\n\n"
        + "\n\n".join(blocks)
        + "\n\nSelect the moments that best serve the brief. For each, choose start "
        "and end timecodes FROM THE CONTEXT SHOWN so the clip contains one complete, "
        "self-contained thought — never start or end mid-sentence. Prefer emotionally "
        "strong, quotable moments; drop candidates that are filler or redundant. "
        "Order the clips so the reel builds like a story: a hook first, then "
        "development, then the strongest emotional beat near the end. The opening "
        "clip must start ON its hook — trim any run-up so the first 2 seconds land.\n"
        "Use the VISUALS line to vary the picture — avoid "
        "placing two clips with the same person in the same framing back-to-back; "
        "alternate faces, files, and shot energy so the reel never feels static. "
        "When two candidates say the same thing, keep the more visually dynamic one.\n"
        + (
            f"The finished piece should run close to {int(target_duration // 60)} minutes "
            "— keep enough material to reach that length; do not over-trim.\n"
            if target_duration else ""
        )
        + "\n"
        "Respond with ONLY a JSON object in exactly this shape:\n"
        '{"clips": [{"candidate": 0, "start": "MM:SS or HH:MM:SS", '
        '"end": "MM:SS or HH:MM:SS", "why": "one line on why this moment earns '
        'its place"}]}\n'
        f"Rules: keep 3 to {len(candidates)} clips, each {int(_CURATE_MIN_CLIP)}-"
        f"{int(max_clip)} seconds."
    )
    raw = _generate(tokenizer, model, llm_prompt, max_new_tokens=900)
    data = _extract_json(raw)

    refined: list[dict] = []
    for item in (data.get("clips") or []):
        if not isinstance(item, dict):
            continue
        try:
            idx = int(item.get("candidate", -1))
        except (TypeError, ValueError):
            continue
        if idx < 0 or idx >= len(windows):
            continue
        mid, filename, ctx_s, ctx_e = windows[idx]
        s = _timecode_to_seconds(item.get("start", candidates[idx]["start_time"]))
        e = _timecode_to_seconds(item.get("end", candidates[idx]["end_time"]))
        s = max(ctx_s, min(float(s), ctx_e))
        e = max(s, min(float(e), ctx_e))
        if e - s < _CURATE_MIN_CLIP:
            e = min(ctx_e, s + _CURATE_MIN_CLIP)
        if e - s > max_clip:
            e = s + max_clip
        if e - s < 2.0:
            continue
        snippet_rows = db.execute(
            text("""
                SELECT text FROM transcript_segments
                WHERE media_id = :mid AND end_time >= :s AND start_time <= :e
                ORDER BY start_time LIMIT 3
            """),
            {"mid": mid, "s": float(s), "e": float(e)},
        ).fetchall()
        snippet = " ".join(r[0] for r in snippet_rows)[:300] or str(item.get("why", ""))[:300]
        refined.append({
            "media_id": mid,
            "filename": filename,
            "start_time": round(float(s), 2),
            "end_time": round(float(e), 2),
            "snippet": snippet,
            "thumbnail_url": candidates[idx].get("thumbnail_url"),
        })

    # Sanity: require a meaningful selection, otherwise keep raw candidates
    if len(refined) < min(3, len(candidates)):
        return None

    # ── Visual variety pass ──────────────────────────────────────────────
    # The LLM sees visuals only as text; verify with the actual SigLIP
    # embeddings and break up any back-to-back near-identical shots, keeping
    # the hook and the closer in place.
    try:
        from tasks.visual_context import diversify_order
        profiles = [
            clip_visual_profile(db, c["media_id"], c["start_time"], c["end_time"])
            for c in refined
        ]
        refined = diversify_order(refined, profiles)
    except Exception:
        pass
    if target_duration:
        # Don't let curation gut a long-form build far below the runtime goal
        # when the raw candidates had the material to reach it.
        raw_total = sum(float(c["end_time"]) - float(c["start_time"]) for c in candidates)
        refined_total = sum(c["end_time"] - c["start_time"] for c in refined)
        if refined_total < 0.6 * min(target_duration, raw_total):
            return None
    return refined


@celery_app.task(bind=True, name="tasks.reel.build_reel", queue="cpu")
def build_reel(self, reel_id: str):
    db = get_session()
    try:
        from sqlalchemy import text
        row = db.execute(
            text("SELECT clips, preset, burn_captions, prompt, target_duration_seconds FROM reel_jobs WHERE id = :rid"),
            {"rid": reel_id},
        ).fetchone()
        if not row:
            raise RuntimeError(f"Reel job {reel_id} not found")
        clips, preset, burn_captions, reel_prompt, target_duration = row
        target_duration = float(target_duration) if target_duration else None
        if isinstance(clips, str):
            clips = json.loads(clips)
        if not clips:
            raise RuntimeError("Reel has no clips to cut")

        _update_reel(db, reel_id, status="running", progress=0.0, error_message=None)

        # ── Creative curation: let the LLM act as a story editor ────────────
        # The API's semantic search only finds *candidate* fragments; without
        # this pass the reel is a pile of mid-sentence shards. The LLM sees
        # each candidate with surrounding transcript context and trims to
        # complete thoughts, drops weak moments, and orders for a real arc.
        if reel_prompt and (reel_prompt or "").strip():
            try:
                curated = _curate_clips(db, reel_prompt.strip(), clips, target_duration)
                if curated:
                    clips = curated
                    _update_reel(db, reel_id, clips=json.dumps(clips))
            except Exception:
                import traceback
                print(f"Reel curation failed, using raw candidates:\n{traceback.format_exc()}")
        _update_reel(db, reel_id, progress=10.0)

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
