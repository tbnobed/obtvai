"""Multi-video story builder.

One creative pass across several assets: mines the strongest moments from each
transcript, then asks the LLM to order them into a single storyline. The result
is written as a clip list (cross-asset clips, story order) plus a narrative.
"""
import json
import math
import uuid
from datetime import datetime
from app import celery_app
from db import get_session


def _set_story(db, story_id: str, **fields):
    from sqlalchemy import text
    sets = ", ".join(f"{k} = :{k}" for k in fields)
    db.execute(
        text(f"UPDATE story_jobs SET {sets} WHERE id = :sid"),
        {**fields, "sid": story_id},
    )
    db.commit()


@celery_app.task(bind=True, name="tasks.story.build_story", queue="gpu")
def build_story(self, story_id: str):
    db = get_session()
    try:
        from sqlalchemy import text
        from tasks.analyze import (
            _load_llm, _generate, _extract_json, _build_chunks,
            _format_timecode, _timecode_to_seconds, CREATIVE_PERSONA, EDITOR_RULES,
        )
        from tasks.creative import _clamp

        row = db.execute(
            text("SELECT asset_ids, prompt, target_duration_seconds FROM story_jobs WHERE id = :sid"),
            {"sid": story_id},
        ).fetchone()
        if not row:
            return
        asset_ids, user_prompt = list(row[0] or []), (row[1] or "").strip()
        target_duration = float(row[2]) if row[2] else None

        # Target-runtime steering: the finished length decides what kind of
        # clips to mine — short pieces want punchy bites, long productions
        # want complete self-contained segments.
        if target_duration is None:
            clip_min, clip_max = 8, 45          # historical default
            seq_lo, seq_hi = 4, 12
        elif target_duration <= 120:
            clip_min, clip_max = 5, 20
            seq_lo, seq_hi = 3, 10
        elif target_duration <= 600:
            clip_min, clip_max = 10, 45
            seq_lo, seq_hi = 4, 16
        elif target_duration <= 1800:
            clip_min, clip_max = 20, 90
            seq_lo, seq_hi = 6, 24
        else:
            # Very long form: clip length and moment count both scale with the
            # target so the accepted range (up to 4 h) is actually reachable.
            clip_min = 30
            clip_max = int(min(300.0, max(180.0, target_duration / 40.0)))
            seq_lo, seq_hi = 8, 120
        if target_duration:
            mid_len = (clip_min + clip_max) / 2.0
            needed = int(math.ceil(target_duration / mid_len)) + 2
            seq_hi = max(seq_lo, min(seq_hi, needed))

        done = db.execute(
            text("SELECT status, clip_list_id FROM story_jobs WHERE id = :sid"),
            {"sid": story_id},
        ).fetchone()
        if done and done[0] == "success" and done[1]:
            return

        # Idempotent retry: drop any clip list from a prior partial run
        prior = db.execute(
            text("SELECT id FROM clip_lists WHERE id = (SELECT clip_list_id FROM story_jobs WHERE id = :sid)"),
            {"sid": story_id},
        ).fetchone()
        if prior:
            db.execute(text("DELETE FROM clips WHERE clip_list_id = :cl"), {"cl": prior[0]})
            db.execute(text("DELETE FROM clip_lists WHERE id = :cl"), {"cl": prior[0]})
            db.execute(
                text("UPDATE story_jobs SET clip_list_id = NULL WHERE id = :sid"),
                {"sid": story_id},
            )
            db.commit()

        _set_story(db, story_id, status="running", progress=2.0)

        assets = []
        for mid in asset_ids:
            a = db.execute(
                text("""
                    SELECT id, filename, duration_seconds, synopsis, creative
                    FROM media_assets WHERE id = :mid
                """),
                {"mid": mid},
            ).fetchone()
            if a:
                assets.append(a)
        if not assets:
            raise RuntimeError("No valid assets for story")

        tokenizer, model = _load_llm()
        _set_story(db, story_id, progress=8.0)

        # ── Per-asset candidate clips ────────────────────────────────────────
        candidates = []  # {key, media_id, filename, start, end, title, why}
        for idx, a in enumerate(assets):
            mid, fname = a[0], a[1]
            duration = float(a[2] or 0)
            creative = a[4] or {}
            suggestions = (creative.get("clip_suggestions") or []) if isinstance(creative, dict) else []

            # Cached generic clip suggestions are only usable when the editor
            # gave no direction AND no runtime target — otherwise they steer
            # every story toward the same recurring themes / clip lengths.
            # With a direction or target, mine the transcript fresh.
            if suggestions and not user_prompt and target_duration is None:
                for c in suggestions[:8]:
                    if c.get("start") is None or c.get("end") is None:
                        continue
                    candidates.append({
                        "media_id": mid, "filename": fname,
                        "start": float(c["start"]), "end": float(c["end"]),
                        "title": c.get("title") or "clip",
                        "why": c.get("reason") or "",
                    })
            else:
                segs = db.execute(
                    text("""
                        SELECT start_time, speaker, text FROM transcript_segments
                        WHERE media_id = :mid ORDER BY start_time
                    """),
                    {"mid": mid},
                ).fetchall()
                if not segs:
                    continue
                if not duration:
                    duration = float(segs[-1][0]) + 30.0
                chunk_cap = 6 if user_prompt else 3
                if target_duration and target_duration > 600:
                    # Long production: cover more of each asset so there is
                    # enough complete-segment material to reach the runtime.
                    chunk_cap = max(chunk_cap, 8)
                if target_duration and target_duration > 1800:
                    chunk_cap = max(chunk_cap, 12)
                chunks = _build_chunks(segs)[:chunk_cap]
                mine_direction = (
                    f"The editor's direction for this story: {user_prompt}\n"
                    "Pick ONLY moments that directly serve that direction — quote or discuss it. "
                    "If a segment has nothing relevant, return an empty clips list.\n\n"
                    if user_prompt else ""
                )
                for chunk_text, c_start, c_end in chunks:
                    prompt = (
                        f"You are a creative video editor. {CREATIVE_PERSONA}\n"
                        f"{EDITOR_RULES}\n"
                        "You are mining raw footage for a "
                        "multi-video story edit.\n\n"
                        f"{mine_direction}"
                        f"Source file: {fname}\n"
                        f"Transcript segment ({_format_timecode(c_start)}–{_format_timecode(c_end)}):\n"
                        f"{chunk_text}\n\n"
                        'Respond with ONLY JSON: {"clips": [{"start": "MM:SS", "end": "MM:SS", '
                        '"title": "short title", "why": "one sentence"}]}\n'
                        f"Rules: 1-3 strongest self-contained moments, each {clip_min}-{clip_max} seconds."
                        + (
                            " The finished production is long-form — prefer complete "
                            "thoughts and full exchanges over quick soundbites."
                            if target_duration and target_duration > 600 else ""
                        )
                    )
                    raw = _generate(tokenizer, model, prompt, max_new_tokens=700)
                    try:
                        data = _extract_json(raw)
                    except (ValueError, json.JSONDecodeError):
                        continue
                    for c in (data.get("clips") or []):
                        if not isinstance(c, dict) or not c.get("title"):
                            continue
                        s = _clamp(_timecode_to_seconds(c.get("start", c_start)), c_start, c_end or duration)
                        e = _clamp(_timecode_to_seconds(c.get("end", s + 20)), s, duration or s + float(clip_max))
                        e = min(e, duration) if duration else e
                        if e - s < 4.0:
                            e = s + float(clip_min)
                        if e - s > float(clip_max):
                            e = s + float(clip_max)
                        if duration:
                            e = min(e, duration)
                        candidates.append({
                            "media_id": mid, "filename": fname,
                            "start": round(s, 1), "end": round(e, 1),
                            "title": str(c["title"]).strip()[:120],
                            "why": str(c.get("why", "")).strip()[:300],
                        })
            _set_story(db, story_id, progress=round(8.0 + 62.0 * (idx + 1) / len(assets), 1))

        if not candidates:
            raise RuntimeError("No usable moments found in the selected assets")

        # ── Reduce: order into one storyline ─────────────────────────────────
        from tasks.visual_context import clip_visual_profile, describe_profile, diversify_order

        profiles_by_key: dict[str, dict] = {}
        for i, c in enumerate(candidates):
            c["key"] = f"C{i + 1}"
            try:
                profile = clip_visual_profile(db, c["media_id"], c["start"], c["end"])
            except Exception:
                profile = {"people": [], "scene_count": 0, "vector": None}
            profiles_by_key[c["key"]] = profile
            c["visual"] = describe_profile(profile)
        listing = "\n".join(
            f"{c['key']}: [{c['filename']} {_format_timecode(c['start'])}–{_format_timecode(c['end'])}] "
            f"{c['title']} — {c['why']} (visuals: {c.get('visual', 'no visual data')})"
            for c in candidates
        )[:9000]
        direction = (
            f"\nEditorial direction from the editor (TOP PRIORITY): {user_prompt}\n"
            "Build the entire story around this direction. Prefer moments that serve it, "
            "drop moments that don't, and make the title and narrative reflect it — "
            "do not fall back to generic themes.\n"
            if user_prompt else ""
        )
        reduce_prompt = (
            f"You are a senior story editor. {CREATIVE_PERSONA}\n"
            f"{EDITOR_RULES}\n"
            "You are assembling ONE story from moments pulled "
            f"across {len(assets)} different videos.{direction}\n"
            f"Available moments:\n{listing}\n\n"
            "Respond with ONLY JSON, exactly this shape:\n"
            "{\n"
            '  "title": "story title",\n'
            '  "narrative": "3-6 sentences: the storyline this cut tells and why this order works",\n'
            '  "sequence": [{"key": "C1", "role": "why this moment sits here (opener, context, turn, payoff...)"}]\n'
            "}\n\n"
            + (
                f"The finished piece should run close to "
                f"{int(target_duration // 60)} minute(s) "
                f"({int(target_duration)} seconds) — pick enough moments to "
                "reach that runtime; do not over-trim.\n"
                if target_duration else ""
            )
            + f"Rules: choose {seq_lo}-{seq_hi} moments, order them for story (not source order), "
            "you may interleave moments from different videos, drop weak or redundant ones. "
            "Cut like a real editor: use the visuals notes to vary the picture — avoid "
            "back-to-back moments showing the same person in the same framing; alternate "
            "faces and source files so the sequence never feels static."
        )
        raw = _generate(tokenizer, model, reduce_prompt, max_new_tokens=1200)
        _set_story(db, story_id, progress=85.0)

        by_key = {c["key"]: c for c in candidates}
        title, narrative, ordered = None, None, []
        try:
            data = _extract_json(raw)
            title = str(data.get("title", "")).strip()[:150] or None
            narrative = str(data.get("narrative", "")).strip()[:2000] or None
            for item in (data.get("sequence") or []):
                key = item.get("key") if isinstance(item, dict) else None
                if key in by_key and by_key[key] not in ordered:
                    c = by_key[key]
                    c["role"] = (str(item.get("role", "")).strip()[:200] or None)
                    ordered.append(c)
        except (ValueError, json.JSONDecodeError):
            pass
        if not ordered:
            # Fallback: chronological within each asset, assets in given order
            ordered = sorted(candidates, key=lambda c: (asset_ids.index(c["media_id"]), c["start"]))[:seq_hi]
        # Visual variety pass: break up back-to-back near-identical shots
        # (verified against the real SigLIP embeddings, not the LLM's guess).
        try:
            ordered = diversify_order(ordered, [profiles_by_key.get(c["key"], {}) for c in ordered])
        except Exception:
            pass
        title = title or "Untitled story"

        # ── Write result as a clip list ──────────────────────────────────────
        cl_id = str(uuid.uuid4())
        proj_row = db.execute(
            text("SELECT project_id FROM story_jobs WHERE id = :sid"),
            {"sid": story_id},
        ).fetchone()
        db.execute(
            text("""
                INSERT INTO clip_lists (id, name, description, project_id, created_at)
                VALUES (:id, :name, :descr, :pid, :now)
            """),
            {"id": cl_id, "name": f"Story — {title}"[:200],
             "descr": (narrative or "")[:2000],
             "pid": proj_row[0] if proj_row else None,
             "now": datetime.utcnow()},
        )
        for pos, c in enumerate(ordered):
            db.execute(
                text("""
                    INSERT INTO clips (id, clip_list_id, media_id, start_time, end_time,
                                       label, notes, position)
                    VALUES (:id, :cl, :mid, :s, :e, :label, :notes, :pos)
                """),
                {"id": str(uuid.uuid4()), "cl": cl_id, "mid": c["media_id"],
                 "s": float(c["start"]), "e": float(c["end"]),
                 "label": c["title"][:200], "notes": c.get("role"), "pos": pos},
            )
        # Link the clip list in the same transaction so a crash after commit
        # leaves no orphan (the retry cleanup above keys off clip_list_id)
        db.execute(
            text("UPDATE story_jobs SET clip_list_id = :cl WHERE id = :sid"),
            {"cl": cl_id, "sid": story_id},
        )
        db.commit()

        _set_story(
            db, story_id,
            status="success", progress=100.0,
            title=title, narrative=narrative, clip_list_id=cl_id,
            finished_at=datetime.utcnow(),
        )

    except Exception as e:
        db.rollback()
        try:
            _set_story(db, story_id, status="error", error_message=str(e)[:2000],
                       finished_at=datetime.utcnow())
        except Exception:
            pass
        raise
    finally:
        db.close()
