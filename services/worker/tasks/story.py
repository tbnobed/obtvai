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


def _segments_between(db, media_id: str, start: float, end: float):
    from sqlalchemy import text
    return db.execute(
        text("""
            SELECT start_time, end_time, speaker, text FROM transcript_segments
            WHERE media_id = :mid AND end_time > :s AND start_time < :e
            ORDER BY start_time
        """),
        {"mid": media_id, "s": start, "e": end},
    ).fetchall()


_TERMINALS = (".", "!", "?", '."', '!"', '?"', "…", ".'", "!'", "?'")


def _snap_to_sentences(db, media_id: str, start: float, end: float,
                       clip_max: float, duration: float | None):
    """Align a clip to transcript boundaries so it never cuts mid-sentence.

    Start snaps back to the beginning of the segment that is speaking at
    `start`; end extends forward through segments until one closes a sentence
    (terminal punctuation) or the extension budget runs out.
    """
    from sqlalchemy import text
    rows = db.execute(
        text("""
            SELECT start_time, end_time, text FROM transcript_segments
            WHERE media_id = :mid AND end_time > :s - 15 AND start_time < :e + 60
            ORDER BY start_time
        """),
        {"mid": media_id, "s": start, "e": end},
    ).fetchall()
    if not rows:
        return start, end
    new_start, new_end = start, end
    for r in rows:
        s_t, e_t = float(r[0]), float(r[1])
        if s_t <= start < e_t:
            new_start = s_t          # don't start mid-sentence
            break
        if start <= s_t <= end:
            new_start = s_t          # start exactly on the next spoken line
            break
        if s_t > end:
            # No speech inside the window at all — don't drift the clip onto
            # unrelated later speech; leave it as mined.
            return start, end
    # Hard cap on the final clip length: snapping may complete a sentence but
    # must never balloon the clip far past the mined intent.
    hard_max = max(clip_max * 1.5, (end - new_start) + 12.0)
    for r in rows:
        s_t, e_t, seg_text = float(r[0]), float(r[1]), (r[2] or "").strip()
        if e_t <= new_start:
            continue
        if e_t <= end:
            new_end = max(new_end, e_t)
            continue
        # Segment crosses or follows the cut point: keep extending until a
        # sentence actually closes, within the length cap.
        candidate_end = min(e_t, new_start + hard_max)
        if candidate_end <= new_end:
            break
        new_end = candidate_end
        if seg_text.endswith(_TERMINALS) or candidate_end < e_t:
            break
    new_end = min(new_end, new_start + hard_max)
    if duration:
        new_end = min(new_end, duration)
    if new_end - new_start < 1.0:
        return start, end
    return round(new_start, 1), round(new_end, 1)


def _extend_forward(db, media_id: str, end: float, want: float) -> float:
    """Grow a clip's end forward through complete transcript sentences.

    Extends toward `want` seconds, finishing the sentence in progress near the
    target (up to 10s past it) rather than cutting mid-thought.
    """
    from sqlalchemy import text
    rows = db.execute(
        text("""
            SELECT start_time, end_time, text FROM transcript_segments
            WHERE media_id = :mid AND end_time > :e AND start_time < :w + 30
            ORDER BY start_time
        """),
        {"mid": media_id, "e": end, "w": want},
    ).fetchall()
    new_end = end
    for r in rows:
        s_t, e_t, seg_text = float(r[0]), float(r[1]), (r[2] or "").strip()
        if s_t >= want:
            break
        new_end = max(new_end, min(e_t, want + 10.0))
        if e_t <= want + 10.0 and seg_text.endswith(_TERMINALS) and new_end >= want - 5.0:
            break
    return round(new_end, 1)


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

        # Project context from the Find tab: the working script steers both
        # the mining and the final ordering.
        proj_ctx = db.execute(
            text("""
                SELECT p.script FROM projects p
                JOIN story_jobs s ON s.project_id = p.id
                WHERE s.id = :sid
            """),
            {"sid": story_id},
        ).fetchone()
        working_script = ((proj_ctx[0] or "") if proj_ctx else "").strip()[:3000]
        script_block = (
            "The editor's working script/rundown for this production:\n---\n"
            f"{working_script}\n---\n"
            "Prefer moments that cover the script's lines and beats.\n\n"
            if working_script else ""
        )

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

        # Clips the editor collected from search in the Find tab are
        # hand-picked footage — seed them as strong candidates (lists
        # generated by earlier story runs are excluded).
        picked_rows = db.execute(
            text("""
                SELECT c.media_id, m.filename, c.start_time, c.end_time, c.label, c.notes
                FROM clips c
                JOIN clip_lists cl ON cl.id = c.clip_list_id
                JOIN media_assets m ON m.id = c.media_id
                WHERE cl.project_id = (SELECT project_id FROM story_jobs WHERE id = :sid)
                  AND cl.id NOT IN (
                      SELECT clip_list_id FROM story_jobs WHERE clip_list_id IS NOT NULL
                  )
                ORDER BY cl.created_at, c.position
            """),
            {"sid": story_id},
        ).fetchall()
        allowed = set(asset_ids)
        for pr in picked_rows[:60]:
            if pr[0] not in allowed:
                continue
            s_t, e_t = float(pr[2] or 0), float(pr[3] or 0)
            if e_t - s_t < 1.0:
                continue
            candidates.append({
                "media_id": pr[0], "filename": pr[1],
                "start": round(s_t, 1), "end": round(e_t, 1),
                "title": ((pr[4] or "").strip() or "Editor-picked clip")[:120],
                "why": ((pr[5] or "").strip() or "Hand-picked from search in Find")[:300],
                "picked": True,
            })
        for idx, a in enumerate(assets):
            mid, fname = a[0], a[1]
            duration = float(a[2] or 0)
            creative = a[4] or {}
            suggestions = (creative.get("clip_suggestions") or []) if isinstance(creative, dict) else []

            # Cached generic clip suggestions are only usable when the editor
            # gave no direction AND no runtime target — otherwise they steer
            # every story toward the same recurring themes / clip lengths.
            # With a direction or target, mine the transcript fresh.
            if suggestions and not user_prompt and not working_script and target_duration is None:
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
                        f"{script_block}"
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
                        if e - s < float(clip_min):
                            # Enforce the target-driven minimum, not just a
                            # sanity floor — short-form bites can't add up to a
                            # long-form runtime.
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

        # Snap every candidate to transcript boundaries so no clip starts or
        # ends mid-sentence, and attach what is actually said so ordering can
        # follow the conversation, not just the titles.
        durations = {a[0]: float(a[2] or 0) for a in assets}
        for c in candidates:
            s, e = _snap_to_sentences(
                db, c["media_id"], c["start"], c["end"],
                float(clip_max), durations.get(c["media_id"]) or None,
            )
            c["start"], c["end"] = s, e
            segs_c = _segments_between(db, c["media_id"], s, e)
            spoken = " ".join((r[3] or "").strip() for r in segs_c).strip()
            c["spoken"] = spoken[:220] + ("…" if len(spoken) > 220 else "")

        # Drop exact duplicates created by snapping (two mined moments can
        # collapse onto the same sentence span).
        seen_spans = set()
        deduped = []
        for c in candidates:
            span = (c["media_id"], c["start"], c["end"])
            if span in seen_spans:
                continue
            seen_spans.add(span)
            deduped.append(c)
        candidates = deduped

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
        # Build the listing without ever dropping candidates: if the full
        # version is over budget, shrink the per-candidate detail (SAYS quote,
        # then visuals) instead of cutting the tail of the list.
        def _listing_line(c, says_chars, with_visuals):
            spoken = (c.get("spoken") or "")[:says_chars].strip()
            return (
                f"{c['key']}: {'[EDITOR-PICKED] ' if c.get('picked') else ''}"
                f"[{c['filename']} {_format_timecode(c['start'])}–{_format_timecode(c['end'])}] "
                f"{c['title']} — {c['why']}"
                + (f' | SAYS: "{spoken}"' if spoken else "")
                + (f" (visuals: {c.get('visual', 'no visual data')})" if with_visuals else "")
            )
        listing = ""
        for says_chars, with_visuals in ((220, True), (120, True), (80, False), (0, False)):
            listing = "\n".join(_listing_line(c, says_chars, with_visuals) for c in candidates)
            if len(listing) <= 12000:
                break
        direction = (
            f"\nEditorial direction from the editor (TOP PRIORITY): {user_prompt}\n"
            "Build the entire story around this direction. Prefer moments that serve it, "
            "drop moments that don't, and make the title and narrative reflect it — "
            "do not fall back to generic themes.\n"
            if user_prompt else ""
        )
        script_ctx = (
            f"\nThe editor's working script for this production:\n---\n{working_script}\n---\n"
            "THE SCRIPT IS THE BLUEPRINT: your sequence must walk the script's beats "
            "in the script's order. For every beat, pick the moment(s) whose SAYS "
            "quote covers or supports that beat; skip a beat only when no moment "
            "covers it. Do not reorder beats and do not build a different story.\n"
            if working_script else ""
        )
        flow_rule = (
            "FOLLOW THE SCRIPT ABOVE — beat order is the top editing rule. Within "
            "each beat, order moments so the spoken words connect naturally. "
            if working_script else
            "CONVERSATIONAL FLOW IS THE TOP EDITING RULE: read each moment's SAYS quote and "
            "order the sequence so the spoken words connect — every moment must pick up an "
            "idea, question, or claim from the one before it (answer it, build on it, or "
            "counter it). Never place a moment whose words have no link to its neighbours; "
            "drop it instead. A moment that opens mid-thought must directly follow a moment "
            "that sets up that thought. The finished cut should read like ONE continuous "
            "conversation or narration when the SAYS quotes are read in order. "
        )
        reduce_prompt = (
            f"You are a senior story editor. {CREATIVE_PERSONA}\n"
            f"{EDITOR_RULES}\n"
            "You are assembling ONE story from moments pulled "
            f"across {len(assets)} different videos.{direction}{script_ctx}\n"
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
            "Moments tagged [EDITOR-PICKED] were hand-selected from search by the editor — "
            "strongly prefer including them. "
            + flow_rule +
            "Then, within that flow, use the visuals notes to vary the picture — avoid "
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

        # ── Runtime fill: the cut must actually reach the target ────────────
        # The LLM routinely over-trims; a 20-minute ask must not ship at 3.
        if target_duration:
            def _total(seq):
                return sum(float(c["end"]) - float(c["start"]) for c in seq)

            def _overlaps(c, seq):
                return any(
                    o is not c and o["media_id"] == c["media_id"]
                    and float(o["start"]) < float(c["end"])
                    and float(c["start"]) < float(o["end"])
                    for o in seq
                )

            # 1) Put dropped candidates back — each after the last kept clip
            #    from the same source that precedes it, so flow isn't scrambled.
            used = {c["key"] for c in ordered}
            leftovers = sorted(
                (c for c in candidates if c["key"] not in used),
                key=lambda c: (asset_ids.index(c["media_id"]), float(c["start"])),
            )
            for c in leftovers:
                if _total(ordered) >= target_duration * 0.95:
                    break
                if _overlaps(c, ordered):
                    continue
                pos = None
                for i, o in enumerate(ordered):
                    if o["media_id"] == c["media_id"] and float(o["start"]) < float(c["start"]):
                        pos = i
                ordered.insert(pos + 1 if pos is not None else len(ordered), c)

            # 2) Still short (candidate pool too small): grow clips forward
            #    through complete sentences until the target is reached or the
            #    footage runs out. Never grow into the next kept clip.
            for _ in range(6):
                deficit = target_duration * 0.95 - _total(ordered)
                if deficit <= 0:
                    break
                grew = False
                for c in ordered:
                    deficit = target_duration * 0.95 - _total(ordered)
                    if deficit <= 0:
                        break
                    c_end = float(c["end"])
                    ceiling = durations.get(c["media_id"]) or float("inf")
                    for o in ordered:
                        if o is not c and o["media_id"] == c["media_id"] \
                                and float(o["start"]) >= c_end:
                            ceiling = min(ceiling, float(o["start"]))
                    want = min(c_end + min(90.0, deficit), ceiling)
                    if want <= c_end + 2.0:
                        continue
                    new_end = min(_extend_forward(db, c["media_id"], c_end, want), ceiling)
                    if new_end > c_end + 1.0:
                        c["end"] = round(new_end, 1)
                        grew = True
                if not grew:
                    break

        # ── Working script: verbatim transcript of the cut, in story order ──
        # This is what the story actually says when played top to tail — the
        # editor's proof that the conversation flows and each beat is complete.
        _set_story(db, story_id, progress=90.0)
        script_lines = []
        for pos, c in enumerate(ordered):
            seg_rows = _segments_between(db, c["media_id"], c["start"], c["end"])
            parts = []
            cur_speaker, cur_text = None, []
            for r in seg_rows:
                spk = (r[2] or "").strip() or "SPEAKER"
                t = (r[3] or "").strip()
                if not t:
                    continue
                if spk != cur_speaker and cur_text:
                    parts.append(f"{cur_speaker}: {' '.join(cur_text)}")
                    cur_text = []
                cur_speaker = spk
                cur_text.append(t)
            if cur_text:
                parts.append(f"{cur_speaker}: {' '.join(cur_text)}")
            head = (
                f"[{pos + 1}] {c['filename']} "
                f"{_format_timecode(c['start'])}–{_format_timecode(c['end'])}"
                + (f" — {c['role']}" if c.get("role") else "")
            )
            body = "\n".join(parts) if parts else "(no dialogue — visual moment)"
            script_lines.append(f"{head}\n{body}")
        assembled_transcript = "\n\n".join(script_lines)

        story_script = assembled_transcript
        try:
            if len(assembled_transcript) > 9000:
                # Too long to hand the LLM whole — the verbatim assembly IS the
                # working script; never polish from a truncated view (that
                # silently drops tail clips).
                raise ValueError("transcript too long for polish pass")
            script_prompt = (
                f"You are a broadcast script editor. {CREATIVE_PERSONA}\n"
                f"Story title: {title}\n"
                f"Storyline: {narrative or ''}\n\n"
                "Below is the verbatim transcript of an assembled cut, clip by clip, "
                "in final story order:\n---\n"
                f"{assembled_transcript}\n---\n\n"
                "Write the WORKING SCRIPT for this cut. Keep every clip, in this exact "
                "order, with its [N] header line unchanged. Under each header keep the "
                "spoken dialogue VERBATIM (do not rewrite quotes), and where a transition "
                "between clips needs help, add a single short 'VO:' or 'TRANSITION:' line "
                "between them so the piece flows as one continuous story. "
                "Respond with ONLY the script text, no JSON, no commentary."
            )
            raw_script = _generate(tokenizer, model, script_prompt, max_new_tokens=2400)
            raw_script = (raw_script or "").strip()
            # Guard: the polished version must keep EVERY clip header — a
            # working script that silently drops clips is worse than the
            # verbatim assembly.
            kept = sum(1 for pos in range(len(ordered)) if f"[{pos + 1}]" in raw_script)
            if raw_script and kept == len(ordered):
                story_script = raw_script
        except Exception:
            pass
        story_script = story_script[:20000]

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
            script=story_script or None,
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
