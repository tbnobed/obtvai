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

# Pace = hard cutting constraint, enforced in code after the LLM pass.
# (min_len, max_len) per clip in seconds. The LLM suggests; the assembler
# splits anything over max_len at scene boundaries or sentence gaps.
_PACE_LIMITS = {
    "fast": (2.0, 6.0),
    "normal": (2.0, 15.0),
    "cinematic": (3.0, 40.0),
}


def _cut_points(db, media_id: str, start: float, end: float) -> list[tuple[float, int]]:
    """Candidate split points inside (start, end), each with a priority:
    0 = scene boundary (best — a real picture cut), 1 = sentence gap
    (transcript segment boundary — cuts between spoken thoughts)."""
    from sqlalchemy import text
    points: list[tuple[float, int]] = []
    rows = db.execute(
        text("""
            SELECT start_time FROM scenes
            WHERE media_id = :mid AND start_time > :s AND start_time < :e
            ORDER BY start_time
        """),
        {"mid": media_id, "s": start + 0.25, "e": end - 0.25},
    ).fetchall()
    points.extend((float(r[0]), 0) for r in rows)
    rows = db.execute(
        text("""
            SELECT end_time FROM transcript_segments
            WHERE media_id = :mid AND end_time > :s AND end_time < :e
            ORDER BY end_time
        """),
        {"mid": media_id, "s": start + 0.25, "e": end - 0.25},
    ).fetchall()
    points.extend((float(r[0]), 1) for r in rows)
    points.sort()
    return points


def _split_clip(db, clip: dict, min_len: float, max_len: float) -> list[dict]:
    """Split one overlong clip into pace-compliant pieces. Prefers scene
    boundaries, then sentence gaps; hard-cuts at max_len only as a last
    resort. Pieces shorter than min_len are merged backward."""
    start = float(clip["start_time"])
    end = float(clip["end_time"])
    if end - start <= max_len:
        return [clip]

    points = _cut_points(db, clip["media_id"], start, end)
    pieces: list[tuple[float, float]] = []
    cur = start
    while end - cur > max_len:
        window = [(t, prio) for t, prio in points if cur + min_len <= t <= cur + max_len]
        if window:
            # Best cut in the window: scene boundary beats sentence gap;
            # among equals take the latest (longest compliant piece).
            cut = max(window, key=lambda p: (-p[1], p[0]))[0]
        else:
            cut = cur + max_len  # no natural cut — enforce anyway
        pieces.append((cur, cut))
        cur = cut
    pieces.append((cur, end))

    # A too-short tail: merge into the previous piece when the merge still
    # fits the hard cap, else rebalance the last two pieces evenly (both stay
    # within max_len and above min_len whenever the combined span allows it).
    if len(pieces) > 1 and pieces[-1][1] - pieces[-1][0] < min_len:
        prev_s, _prev_e = pieces[-2]
        _tail_s, tail_e = pieces[-1]
        span = tail_e - prev_s
        pieces.pop()
        if span <= max_len:
            pieces[-1] = (prev_s, tail_e)
        elif span >= 2 * min_len:
            mid = prev_s + span / 2
            pieces[-1] = (prev_s, mid)
            pieces.append((mid, tail_e))
        # else: span > max_len but can't make two >= min_len pieces — drop the
        # sliver below (hard cap wins over keeping every last second).

    out = []
    for s, e in pieces:
        if e - s < min_len:
            continue
        piece = dict(clip)
        piece["start_time"] = round(s, 2)
        piece["end_time"] = round(e, 2)
        out.append(piece)
    if not out:
        # Degenerate case: keep the strongest max_len window instead of ever
        # emitting an overlong clip — the cap is a hard constraint.
        piece = dict(clip)
        piece["start_time"] = round(start, 2)
        piece["end_time"] = round(start + max_len, 2)
        out.append(piece)
    return out


def _enforce_pace(db, clips: list[dict], pace: str | None) -> list[dict]:
    """Hard pacing constraint applied AFTER curation: no clip may exceed the
    pace's max length. Order is preserved; split pieces stay adjacent."""
    limits = _PACE_LIMITS.get(pace or "normal")
    if not limits:
        limits = _PACE_LIMITS["normal"]
    min_len, max_len = limits
    out: list[dict] = []
    for c in clips:
        try:
            out.extend(_split_clip(db, c, min_len, max_len))
        except Exception:
            # Cut-point lookup failed — the cap is still hard: split evenly
            # into equal pieces no longer than max_len.
            s, e = float(c["start_time"]), float(c["end_time"])
            span = e - s
            if span <= max_len:
                out.append(c)
                continue
            import math
            n = math.ceil(span / max_len)
            step = span / n
            for i in range(n):
                piece = dict(c)
                piece["start_time"] = round(s + i * step, 2)
                piece["end_time"] = round(min(e, s + (i + 1) * step), 2)
                if piece["end_time"] - piece["start_time"] >= min_len:
                    out.append(piece)
    return out


def _reference_examples(db, limit: int = 3) -> str:
    """Few-shot feedback loop: summarize recently thumbs-up'd reels (and what
    the editor rejected) so the LLM learns the house style from real ratings.
    No fine-tuning — liked examples are simply shown as references."""
    from sqlalchemy import text
    rows = db.execute(
        text("""
            SELECT prompt, clips, candidate_clips, rating FROM reel_jobs
            WHERE rating IN ('up', 'down') AND status = 'success'
            ORDER BY (rating = 'up') DESC, created_at DESC
            LIMIT :n
        """),
        {"n": limit * 2},
    ).fetchall()
    ups, downs = [], []
    for r_prompt, r_clips, r_cands, r_rating in rows:
        clips_ = json.loads(r_clips) if isinstance(r_clips, str) else (r_clips or [])
        cands_ = json.loads(r_cands) if isinstance(r_cands, str) else (r_cands or [])
        if not clips_:
            continue
        lens = [float(c["end_time"]) - float(c["start_time"]) for c in clips_]
        snippets = "; ".join(
            f'"{(c.get("snippet") or "")[:90]}"' for c in clips_[:3] if c.get("snippet")
        )
        line = (
            f'- Brief: "{r_prompt[:120]}" — kept {len(clips_)}'
            + (f" of {len(cands_)} candidates" if cands_ else " clips")
            + f", clip lengths {min(lens):.0f}-{max(lens):.0f}s"
            + (f". Sample kept moments: {snippets}" if snippets else "")
        )
        (ups if r_rating == "up" else downs).append(line)
    parts = []
    if ups:
        parts.append(
            "Reference cuts the editor RATED UP — match this selection style:\n"
            + "\n".join(ups[:limit])
        )
    if downs:
        parts.append(
            "Cuts the editor RATED DOWN — avoid whatever made these weak:\n"
            + "\n".join(downs[:limit])
        )
    return "\n".join(parts)


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

    # Feedback loop: show recently rated reels as few-shot references.
    references = ""
    try:
        references = _reference_examples(db)
    except Exception:
        pass

    tokenizer, model = _load_llm()
    llm_prompt = (
        f"You are a senior video editor cutting a highlight reel. {CREATIVE_PERSONA}\n"
        f"{EDITOR_RULES}\n"
        + (f"{references}\n\n" if references else "")
        + f'Editorial brief: "{prompt}"\n\n'
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
            text("SELECT clips, preset, burn_captions, prompt, target_duration_seconds, pace FROM reel_jobs WHERE id = :rid"),
            {"rid": reel_id},
        ).fetchone()
        if not row:
            raise RuntimeError(f"Reel job {reel_id} not found")
        clips, preset, burn_captions, reel_prompt, target_duration, pace = row
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

        # ── Pace enforcement: hard constraint, not a vibe ────────────────────
        # The LLM suggests; the assembler enforces. Anything longer than the
        # pace's max clip length is split at scene boundaries or sentence gaps.
        paced = _enforce_pace(db, clips, pace)
        if paced != clips:
            clips = paced
            _update_reel(db, reel_id, clips=json.dumps(clips))
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
