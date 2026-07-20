"""Cross-asset person identification.

Matches this asset's diarized speakers (voice embeddings) and face clusters
(FaceNet centroids) against the global `people` table, creating new people
when nothing matches. Then regenerates each touched person's AI profile
(name, speech style, key topics) with the local LLM.

Idempotent: appearances for the asset are rebuilt from scratch on every run.
Serialized globally via a Postgres advisory lock so concurrent runs (diarize
and face_detect both trigger it) cannot create duplicate people.
"""
import json
import os
import time
import uuid
from datetime import datetime
from sqlalchemy.exc import OperationalError
from app import celery_app
from db import get_session
from tasks.base import update_job, append_log

VOICE_SIM_THRESHOLD = 0.75
FACE_SIM_THRESHOLD = 0.55   # ArcFace (InsightFace buffalo_l) similarities run
                            # lower than FaceNet's: same-person ~0.5-0.8,
                            # different-person <0.3. The FaceNet-era 0.70
                            # would reject almost every true match.
FACE_ATTACH_OVERLAP = 0.25
FACE_VETO_THRESHOLD = 0.15  # ArcFace same-person sims run 0.5-0.8, different-person
                            # <0.3. If a voice match's attached face scores below
                            # this against the person's face, they are visibly
                            # different people — reject the voice match instead of
                            # blending a wrong voice/face into the person.
BLEND_WEIGHT_CAP = 20       # an established person's embedding moves at most
                            # 1/(cap+1) per new asset, so one bad match can't
                            # poison a 41-asset identity the way a 50/50 blend did
MANUAL_BLEND_FLOOR = 5.0    # manually named people keep their embeddings after a
                            # library wipe but lose their appearance rows, so
                            # n_prev=0 would let the first re-match shift a curated
                            # identity 50% — floor their weight instead
BLEND_WEIGHT_FLOOR = 3.0    # a brand-new person (1 prior appearance) used to shift
                            # 50% on its very next match, so one early cross-match
                            # re-poisoned a freshly rebuilt print immediately; floor
                            # the weight so any single asset moves a print ≤25%
VOICE_VETO_THRESHOLD = 0.2  # pyannote same-speaker sims run ~0.75+; if a face
                            # match's voices score below this, the attached face
                            # is likely the wrong on-screen person — reject
FACE_ONLY_MIN_SECONDS = 10.0    # face-only cluster must be on screen this long...
FACE_ONLY_MIN_APPEARANCES = 3   # ...AND seen in at least this many scenes to become a person
                                # (was OR — hands/blurs seen briefly in a few scenes
                                # became junk "people" with 0 speaking time)
_PROFILE_CHARS = 12000


def _cosine(a, b) -> float:
    import numpy as np
    va, vb = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    na, nb = np.linalg.norm(va), np.linalg.norm(vb)
    if na == 0 or nb == 0:
        return -1.0
    return float(np.dot(va, vb) / (na * nb))


def _blend(old, new, old_weight: float = 1.0):
    """Weighted running average of two embeddings, renormalized.

    old_weight ~ how many prior assets the old embedding represents (caller
    caps it): the new sample moves the result by 1/(old_weight+1). The old
    equal-weight blend let a single wrong match shift an established person's
    embedding by 50%, turning it into a centroid that matched everyone.
    """
    import numpy as np
    if old is None:
        return [float(x) for x in new]
    if new is None:
        return [float(x) for x in old]
    w = max(1.0, float(old_weight))
    v = (np.asarray(old, dtype=float) * w + np.asarray(new, dtype=float)) / (w + 1.0)
    n = np.linalg.norm(v)
    if n > 0:
        v = v / n
    return [float(x) for x in v]


def _extract_name(db, media_id: str, speaker: str, tokenizer, model) -> str | None:
    from sqlalchemy import text
    from tasks.analyze import _generate, _extract_json
    rows = db.execute(
        text("""
            SELECT speaker, text FROM transcript_segments
            WHERE media_id = :mid ORDER BY start_time LIMIT 60
        """),
        {"mid": media_id},
    ).fetchall()
    if not rows:
        return None
    lines = [f"{'>>' if spk == speaker else '  '} {spk or 'Speaker'}: {txt}" for spk, txt in rows]
    prompt = (
        "Below is the start of a video transcript. Lines starting with '>>' are "
        f"spoken by the speaker labeled {speaker}.\n"
        "If the transcript reveals this speaker's real name (they introduce "
        "themselves, or someone addresses them by name), return it. Otherwise "
        "return null. Do not guess.\n"
        'Respond with ONLY a JSON object: {"name": "First Last"} or {"name": null}\n\n'
        + "\n".join(lines)[:8000]
    )
    try:
        result = _extract_json(_generate(tokenizer, model, prompt, max_new_tokens=100))
        name = result.get("name")
        if isinstance(name, str):
            name = name.strip()
            if 1 < len(name) <= 60 and name.lower() not in ("null", "unknown", "speaker"):
                return name
    except Exception:
        pass
    return None


def _web_search_context(name: str, db=None, job_id: str = "") -> str:
    """Fetch top SearXNG results for the person's name and format them as
    LLM context. Returns "" when SearXNG is unconfigured/unreachable — the
    profile then generates from transcripts alone. Only the person's name
    leaves the network, matching the trends feature's privacy posture."""
    import httpx
    from config import SEARXNG_URL
    if not SEARXNG_URL:
        if db is not None:
            append_log(db, job_id, "Web search skipped: SEARXNG_URL not configured")
        return ""
    base = SEARXNG_URL.rstrip("/")
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(
                f"{base}/search",
                params={"q": f'"{name}"', "format": "json"},
            )
            resp.raise_for_status()
            results = (resp.json().get("results") or [])[:6]
    except Exception as exc:
        if db is not None:
            append_log(db, job_id, f"Web search failed ({exc}) — profiling from transcripts only")
        return ""
    lines = []
    for r in results:
        title = str(r.get("title") or "").strip()
        content = str(r.get("content") or "").strip()
        if title or content:
            lines.append(f"- {title}: {content}"[:500])
    if db is not None:
        append_log(db, job_id, f"Web search: {len(lines)} results for '{name}'")
    return "\n".join(lines)[:4000]


def _profile_person(db, person_id: str, tokenizer, model, job_id: str, use_web: bool = False):
    """Regenerate summary / speech_style / key_topics from everything this person has said."""
    from sqlalchemy import text
    from tasks.analyze import _generate, _extract_json
    rows = db.execute(
        text("""
            SELECT ts.text FROM person_appearances pa
            JOIN transcript_segments ts
              ON ts.media_id = pa.media_id AND ts.speaker = pa.speaker_label
            WHERE pa.person_id = :pid AND pa.speaker_label IS NOT NULL
            ORDER BY ts.media_id, ts.start_time
        """),
        {"pid": person_id},
    ).fetchall()
    texts = []
    total = 0
    for (t,) in rows:
        if total + len(t) > _PROFILE_CHARS:
            break
        texts.append(t)
        total += len(t)
    if not texts:
        return
    name_row = db.execute(
        text("SELECT display_name FROM people WHERE id = :pid"), {"pid": person_id}
    ).fetchone()
    display_name = name_row[0] if name_row else "this person"
    # End the read transaction NOW: LLM generation below takes minutes, and an
    # open transaction holding AccessShareLock on transcript_segments/people
    # deadlocks against API startup DDL (ALTER TABLE queues an
    # AccessExclusiveLock, blocking and being blocked in a cycle).
    db.commit()
    web_block = ""
    if use_web:
        ctx = _web_search_context(display_name, db, job_id)
        if ctx:
            web_block = (
                f"\nWeb search results for \"{display_name}\" (these may describe a "
                "DIFFERENT person with the same name — only use facts that are "
                "consistent with what the person says in the transcript below; "
                "if the results clearly match, you may use them to state their "
                "real role/affiliation):\n" + ctx + "\n"
            )
    prompt = (
        f"The following are things {display_name} has said across a video library.\n"
        f"The person's name is {display_name}. Refer to them ONLY by this name, "
        "even if the transcript mentions or suggests other names (those may be "
        "people they are talking about or introducing).\n"
        + web_block +
        "Analyze them and respond with ONLY a JSON object of this exact shape:\n"
        '{"summary": "1-2 sentence bio of who this person appears to be and their role", '
        '"speech_style": "1-2 sentences describing how they speak: tone, pacing, vocabulary, verbal habits", '
        '"key_topics": ["up to 6 short topic phrases they talk about most"]}\n\n'
        + "\n".join(texts)
    )
    try:
        result = _extract_json(_generate(tokenizer, model, prompt, max_new_tokens=400))
    except Exception as e:
        append_log(db, job_id, f"Profile generation failed for {display_name}: {e}")
        return
    topics = result.get("key_topics")
    if not isinstance(topics, list):
        topics = None
    else:
        topics = [str(t)[:80] for t in topics[:6]]
    db.execute(
        text("""
            UPDATE people SET
              summary = :summary,
              speech_style = :style,
              key_topics = CAST(:topics AS jsonb),
              updated_at = :now
            WHERE id = :pid
        """),
        {
            "summary": str(result.get("summary") or "")[:2000] or None,
            "style": str(result.get("speech_style") or "")[:2000] or None,
            "topics": json.dumps(topics) if topics else None,
            "now": datetime.utcnow(),
            "pid": person_id,
        },
    )
    db.commit()


@celery_app.task(bind=True, name="tasks.identify.identify_people", queue="gpu")
def identify_people(self, media_id: str, job_id: str):
    db = get_session()
    locked = False
    try:
        from sqlalchemy import text
        update_job(db, job_id, status="running", started_at=datetime.utcnow(), celery_task_id=self.request.id)

        db.execute(text("SELECT pg_advisory_lock(hashtext('obtv_identify'))"))
        locked = True

        # ── Gather asset-level identity signals ────────────────────────────
        emb_row = db.execute(
            text("SELECT speaker_embeddings FROM media_assets WHERE id = :mid"),
            {"mid": media_id},
        ).fetchone()
        voice_map = (emb_row[0] or {}) if emb_row else {}

        speaker_stats = db.execute(
            text("""
                SELECT speaker,
                       COUNT(*) AS segs,
                       SUM(end_time - start_time) AS secs,
                       MIN(start_time) AS first_at
                FROM transcript_segments
                WHERE media_id = :mid AND speaker IS NOT NULL
                GROUP BY speaker
            """),
            {"mid": media_id},
        ).fetchall()

        clusters = db.execute(
            text("""
                SELECT cluster_id, embedding, thumbnail_url, appearances
                FROM face_clusters
                WHERE media_id = :mid AND embedding IS NOT NULL
            """),
            {"mid": media_id},
        ).fetchall()

        if not speaker_stats and not clusters:
            update_job(db, job_id, status="success", finished_at=datetime.utcnow(), progress=100.0)
            append_log(db, job_id, "No speakers or faces to identify yet")
            return

        # Speaker speaking intervals (for attaching face clusters to speakers)
        speaker_intervals: dict[str, list[tuple[float, float]]] = {}
        for spk, s, e in db.execute(
            text("""
                SELECT speaker, start_time, end_time FROM transcript_segments
                WHERE media_id = :mid AND speaker IS NOT NULL
            """),
            {"mid": media_id},
        ).fetchall():
            speaker_intervals.setdefault(spk, []).append((float(s), float(e)))

        def _overlap_fraction(appearances, intervals) -> float:
            total = 0.0
            overlap = 0.0
            for a in appearances or []:
                a0, a1 = float(a["start_time"]), float(a["end_time"])
                total += max(0.0, a1 - a0)
                for i0, i1 in intervals:
                    overlap += max(0.0, min(a1, i1) - max(a0, i0))
            return overlap / total if total > 0 else 0.0

        cluster_for_speaker: dict[str, tuple] = {}
        attached_clusters = set()
        for row in clusters:
            best_spk, best_frac = None, 0.0
            for spk, intervals in speaker_intervals.items():
                frac = _overlap_fraction(row[3], intervals)
                if frac > best_frac:
                    best_frac, best_spk = frac, spk
            if best_spk and best_frac >= FACE_ATTACH_OVERLAP and best_spk not in cluster_for_speaker:
                cluster_for_speaker[best_spk] = row
                attached_clusters.add(row[0])

        # ── Rebuild this asset's appearances from scratch ──────────────────
        db.execute(
            text("DELETE FROM person_appearances WHERE media_id = :mid"),
            {"mid": media_id},
        )
        db.commit()

        people = db.execute(
            text("SELECT id, display_name, name_source, voice_embedding, face_embedding, thumbnail_url FROM people")
        ).fetchall()
        people = [list(p) for p in people]

        tokenizer = model = None
        touched: list[str] = []
        new_people = 0

        def _ensure_llm():
            nonlocal tokenizer, model
            if model is None:
                from tasks.analyze import _load_llm
                tokenizer, model = _load_llm()
            return tokenizer, model

        # Each diarized speaker in this asset must resolve to a DISTINCT person:
        # two different voices in the same video are never the same person.
        #
        # Assignment is GLOBAL, not first-come-first-served: the old loop
        # processed speakers in arbitrary SQL order and let whichever speaker
        # came first claim a person, even when another speaker in the same
        # video matched that person far more strongly. One such theft cascades
        # into a full rotation — the real owner takes the next-best person,
        # and the last speaker gets a brand-new "Person N". Instead, score
        # every speaker↔person pair first, then hand each person to their
        # STRONGEST claimant (pairs ranked by margin above their threshold, so
        # voice and face scores are comparable).
        assigned_pids: set[str] = set()

        speaker_signals: dict[str, tuple] = {}
        for spk, segs, secs, first_at in speaker_stats:
            cluster = cluster_for_speaker.get(spk)
            speaker_signals[spk] = (
                voice_map.get(spk),
                cluster[1] if cluster else None,
                cluster,
            )

        candidates: list[tuple[float, float, str, int]] = []
        for spk, (voice, face, _cluster) in speaker_signals.items():
            voice_cands: list[tuple[float, float, str, int]] = []
            face_cands: list[tuple[float, float, str, int]] = []
            for idx, p in enumerate(people):
                if voice and p[3]:
                    sim = _cosine(voice, p[3])
                    if sim >= VOICE_SIM_THRESHOLD:
                        # Face veto: a voice match against a visibly different
                        # face is a wrong match (drifted/blended voiceprints
                        # pass 0.75 for the wrong speaker). Reject it rather
                        # than blending a second real person into this identity.
                        if face and p[4]:
                            face_sim = _cosine(face, p[4])
                            if face_sim < FACE_VETO_THRESHOLD:
                                append_log(
                                    db, job_id,
                                    f"Vetoed voice match: speaker {spk} vs {p[1]} "
                                    f"(voice sim {sim:.2f}, but face sim {face_sim:.2f})",
                                )
                                continue
                        rank = (sim - VOICE_SIM_THRESHOLD) / (1.0 - VOICE_SIM_THRESHOLD)
                        voice_cands.append((rank, sim, spk, idx))
                        continue
                if face and p[4]:
                    sim = _cosine(face, p[4])
                    if sim >= FACE_SIM_THRESHOLD:
                        # Voice veto (symmetric to the face veto above): if both
                        # sides have voiceprints and they clearly contradict, the
                        # face cluster was likely attached to the wrong speaker
                        # (e.g. interviewer on screen while the guest talks).
                        if voice and p[3]:
                            voice_sim = _cosine(voice, p[3])
                            if voice_sim < VOICE_VETO_THRESHOLD:
                                append_log(
                                    db, job_id,
                                    f"Vetoed face match: speaker {spk} vs {p[1]} "
                                    f"(face sim {sim:.2f}, but voice sim {voice_sim:.2f})",
                                )
                                continue
                        rank = (sim - FACE_SIM_THRESHOLD) / (1.0 - FACE_SIM_THRESHOLD)
                        face_cands.append((rank, sim, spk, idx))
            # Voice is the primary signal: face-based matches for this speaker
            # only compete when no person voice-matched at all (same semantics
            # as the old two-pass loop).
            candidates.extend(voice_cands if voice_cands else face_cands)

        candidates.sort(key=lambda c: c[0], reverse=True)
        assignment: dict[str, tuple[int, float]] = {}
        for rank, sim, spk, idx in candidates:
            if spk in assignment or people[idx][0] in assigned_pids:
                continue
            assignment[spk] = (idx, sim)
            assigned_pids.add(people[idx][0])

        for spk, segs, secs, first_at in speaker_stats:
            voice, face, cluster = speaker_signals[spk]
            hit = assignment.get(spk)
            match, best_sim = (people[hit[0]], hit[1]) if hit else (None, 0.0)

            if match is None:
                pid = str(uuid.uuid4())
                tok, mdl = _ensure_llm()
                name = _extract_name(db, media_id, spk, tok, mdl)
                if name:
                    name_source = "auto"
                else:
                    count = db.execute(text("SELECT COUNT(*) FROM people")).fetchone()[0]
                    name = f"Person {count + 1}"
                    name_source = None
                db.execute(
                    text("""
                        INSERT INTO people (id, display_name, name_source, thumbnail_url,
                                            voice_embedding, face_embedding, created_at)
                        VALUES (:id, :name, :src, :thumb, CAST(:voice AS jsonb), CAST(:face AS jsonb), :now)
                    """),
                    {
                        "id": pid,
                        "name": name,
                        "src": name_source,
                        "thumb": cluster[2] if cluster else None,
                        "voice": json.dumps([float(x) for x in voice]) if voice else None,
                        "face": json.dumps([float(x) for x in face]) if face else None,
                        "now": datetime.utcnow(),
                    },
                )
                people.append([pid, name, name_source, voice, face, cluster[2] if cluster else None])
                new_people += 1
                append_log(db, job_id, f"New person: {name} (speaker {spk})")
            else:
                pid = match[0]
                # Weight the person's existing embedding by how many assets
                # back it up (current asset's appearances were already deleted
                # above, so this counts prior assets only).
                n_prev = db.execute(
                    text("SELECT COUNT(*) FROM person_appearances WHERE person_id = :pid"),
                    {"pid": pid},
                ).fetchone()[0]
                w = max(BLEND_WEIGHT_FLOOR, float(min(int(n_prev), BLEND_WEIGHT_CAP)))
                if match[2] == "manual":
                    w = max(w, MANUAL_BLEND_FLOOR)
                new_voice = _blend(match[3], voice, w) if voice else match[3]
                new_face = _blend(match[4], face, w) if face else match[4]
                new_thumb = match[5] or (cluster[2] if cluster else None)
                db.execute(
                    text("""
                        UPDATE people SET
                          voice_embedding = CAST(:voice AS jsonb),
                          face_embedding = CAST(:face AS jsonb),
                          thumbnail_url = :thumb,
                          updated_at = :now
                        WHERE id = :pid
                    """),
                    {
                        "voice": json.dumps(new_voice) if new_voice else None,
                        "face": json.dumps(new_face) if new_face else None,
                        "thumb": new_thumb,
                        "now": datetime.utcnow(),
                        "pid": pid,
                    },
                )
                match[3], match[4], match[5] = new_voice, new_face, new_thumb
                append_log(db, job_id, f"Matched speaker {spk} to {match[1]} (sim {best_sim:.2f})")

            db.execute(
                text("""
                    INSERT INTO person_appearances
                      (id, person_id, media_id, speaker_label, face_cluster_id,
                       speaking_seconds, segment_count, first_spoken_at, created_at)
                    VALUES (:id, :pid, :mid, :spk, :cid, :secs, :segs, :first, :now)
                """),
                {
                    "id": str(uuid.uuid4()),
                    "pid": pid,
                    "mid": media_id,
                    "spk": spk,
                    "cid": cluster[0] if cluster else None,
                    "secs": float(secs) if secs is not None else None,
                    "segs": int(segs),
                    "first": float(first_at) if first_at is not None else None,
                    "now": datetime.utcnow(),
                },
            )
            db.commit()
            touched.append(pid)
            assigned_pids.add(pid)

        # Face-only clusters (people seen but never speaking): match against
        # known faces, or create a new person when the cluster is substantial
        # enough (on-screen long enough / seen often enough) to be a real person.
        def _cluster_screen_seconds(appearances) -> float:
            total = 0.0
            for a in appearances or []:
                total += max(0.0, float(a["end_time"]) - float(a["start_time"]))
            return total

        for row in clusters:
            if row[0] in attached_clusters:
                continue
            best_p, best_sim = None, 0.0
            for p in people:
                if p[4]:
                    sim = _cosine(row[1], p[4])
                    if sim >= FACE_SIM_THRESHOLD and sim > best_sim:
                        best_sim, best_p = sim, p
            if best_p is None:
                screen_secs = _cluster_screen_seconds(row[3])
                n_appearances = len(row[3] or [])
                if screen_secs < FACE_ONLY_MIN_SECONDS or n_appearances < FACE_ONLY_MIN_APPEARANCES:
                    append_log(
                        db, job_id,
                        f"Skipped weak face-only cluster {row[0]} ({screen_secs:.1f}s on screen, {n_appearances} appearances)",
                    )
                    continue
                pid = str(uuid.uuid4())
                count = db.execute(text("SELECT COUNT(*) FROM people")).fetchone()[0]
                name = f"Person {count + 1}"
                db.execute(
                    text("""
                        INSERT INTO people (id, display_name, name_source, thumbnail_url,
                                            voice_embedding, face_embedding, created_at)
                        VALUES (:id, :name, NULL, :thumb, NULL, CAST(:face AS jsonb), :now)
                    """),
                    {
                        "id": pid,
                        "name": name,
                        "thumb": row[2],
                        "face": json.dumps([float(x) for x in row[1]]),
                        "now": datetime.utcnow(),
                    },
                )
                db.execute(
                    text("""
                        INSERT INTO person_appearances
                          (id, person_id, media_id, face_cluster_id, created_at)
                        VALUES (:id, :pid, :mid, :cid, :now)
                    """),
                    {"id": str(uuid.uuid4()), "pid": pid, "mid": media_id, "cid": row[0], "now": datetime.utcnow()},
                )
                db.commit()
                people.append([pid, name, None, None, [float(x) for x in row[1]], row[2]])
                new_people += 1
                append_log(
                    db, job_id,
                    f"New person from face-only cluster: {name} ({screen_secs:.1f}s on screen)",
                )
                continue
            existing = db.execute(
                text("SELECT id FROM person_appearances WHERE person_id = :pid AND media_id = :mid"),
                {"pid": best_p[0], "mid": media_id},
            ).fetchone()
            if existing:
                db.execute(
                    text("UPDATE person_appearances SET face_cluster_id = COALESCE(face_cluster_id, :cid) WHERE id = :aid"),
                    {"cid": row[0], "aid": existing[0]},
                )
            else:
                db.execute(
                    text("""
                        INSERT INTO person_appearances
                          (id, person_id, media_id, face_cluster_id, created_at)
                        VALUES (:id, :pid, :mid, :cid, :now)
                    """),
                    {"id": str(uuid.uuid4()), "pid": best_p[0], "mid": media_id, "cid": row[0], "now": datetime.utcnow()},
                )
                touched.append(best_p[0])
                append_log(db, job_id, f"Face-only appearance matched to {best_p[1]} (sim {best_sim:.2f})")
            db.commit()

        # Drop auto-created people that no longer have any appearances (stale
        # from re-runs). Manually named people are never auto-deleted — the
        # user invested in labeling them, so keep them for future matching.
        db.execute(text("""
            DELETE FROM people
            WHERE id NOT IN (SELECT DISTINCT person_id FROM person_appearances)
              AND (name_source IS NULL OR name_source != 'manual')
        """))
        db.commit()

        # ── AI profiles for everyone touched ────────────────────────────────
        # Release the global lock first: matching/writes above are done, and
        # profiling is pure LLM work + per-person UPDATEs that are safe to run
        # concurrently. Holding the lock here serialized all identify jobs and
        # left the second GPU idle during library re-analysis.
        db.execute(text("SELECT pg_advisory_unlock(hashtext('obtv_identify'))"))
        db.commit()
        locked = False

        touched = list(dict.fromkeys(touched))
        if touched:
            update_job(db, job_id, progress=60.0)
            append_log(db, job_id, f"Generating AI profiles for {len(touched)} people...")
            tok, mdl = _ensure_llm()
            for pid in touched:
                # Retry once on deadlock/lock-timeout: transient collisions
                # with API startup migrations or concurrent identify runs.
                for attempt in (1, 2):
                    try:
                        _profile_person(db, pid, tok, mdl, job_id)
                        break
                    except OperationalError as e:
                        db.rollback()
                        if attempt == 2:
                            append_log(db, job_id, f"Profile skipped for {pid}: {e.orig}")
                        else:
                            time.sleep(3)

        update_job(db, job_id, status="success", finished_at=datetime.utcnow(), progress=100.0)
        append_log(
            db, job_id,
            f"Identification complete: {len(speaker_stats)} speakers, {new_people} new people, {len(touched)} profiles updated",
        )

    except Exception as e:
        db.rollback()
        update_job(db, job_id, status="error", error_message=str(e), finished_at=datetime.utcnow())
        raise
    finally:
        if locked:
            try:
                from sqlalchemy import text
                db.execute(text("SELECT pg_advisory_unlock(hashtext('obtv_identify'))"))
                db.commit()
            except Exception:
                pass
        db.close()


def _litterbox_upload(path: str) -> str:
    """Upload a file to litterbox.catbox.moe (expires after 1 hour) and return
    its public URL. Google Lens (SerpAPI) can only fetch images by URL, so the
    face crop must be briefly reachable from the internet."""
    import httpx
    with open(path, "rb") as fh:
        resp = httpx.post(
            "https://litterbox.catbox.moe/resources/internals/api.php",
            data={"reqtype": "fileupload", "time": "1h"},
            files={"fileToUpload": (os.path.basename(path), fh, "image/jpeg")},
            timeout=60.0,
        )
    resp.raise_for_status()
    url = resp.text.strip()
    if not url.startswith("http"):
        raise RuntimeError(f"Unexpected upload response: {url[:200]}")
    return url


@celery_app.task(name="tasks.identify.face_search", queue="cpu")
def face_search(person_id: str, job_id: str = ""):
    """Reverse-search a person's face on the web via Google Lens (SerpAPI).

    Uploads the person's face thumbnail to a 1-hour temporary public host,
    runs a Google Lens visual match search on it, and stores the top
    candidates in people.face_search for the UI to present. A human decides
    what to do with the candidates — nothing is renamed automatically."""
    import httpx
    from datetime import datetime, timezone
    from sqlalchemy import text
    from config import SERPAPI_KEY, THUMBNAILS_DIR

    db = get_session()

    def _store(payload: dict):
        db.rollback()
        db.execute(
            text("UPDATE people SET face_search = CAST(:p AS jsonb) WHERE id = :pid"),
            {"p": json.dumps(payload), "pid": person_id},
        )
        db.commit()

    try:
        row = db.execute(
            text("SELECT thumbnail_url FROM people WHERE id = :pid"),
            {"pid": person_id},
        ).fetchone()
        if row is None:
            return
        if not SERPAPI_KEY:
            _store({"status": "error", "error": "SERPAPI_KEY is not configured on the server"})
            return
        thumb = os.path.join(THUMBNAILS_DIR, os.path.basename(row[0] or ""))
        if not row[0] or not os.path.isfile(thumb):
            _store({"status": "error", "error": "Face thumbnail file not found"})
            return

        image_url = _litterbox_upload(thumb)
        try:
            with httpx.Client(timeout=90.0) as client:
                resp = client.get(
                    "https://serpapi.com/search.json",
                    params={"engine": "google_lens", "url": image_url, "api_key": SERPAPI_KEY},
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as exc:
            # Never persist the raw exception — httpx embeds the full request
            # URL (including api_key) in its message.
            raise RuntimeError(f"SerpAPI returned HTTP {exc.response.status_code}") from None
        if data.get("error"):
            raise RuntimeError(str(data["error"])[:300])

        candidates = []
        for m in (data.get("visual_matches") or [])[:15]:
            title = str(m.get("title") or "").strip()
            link = str(m.get("link") or "").strip()
            if not title or not link:
                continue
            candidates.append({
                "title": title[:200],
                "link": link,
                "source": (str(m.get("source")) if m.get("source") else None),
                "thumbnail": (str(m.get("thumbnail")) if m.get("thumbnail") else None),
            })
        _store({
            "status": "done",
            "searched_at": datetime.now(timezone.utc).isoformat(),
            "candidates": candidates,
        })
    except Exception as exc:
        # Belt and braces: strip any api_key that made it into the message.
        import re
        msg = re.sub(r"api_key=[^&\s'\"]+", "api_key=***", str(exc))
        try:
            _store({"status": "error", "error": msg[:300]})
        except Exception:
            pass
        raise
    finally:
        db.close()


@celery_app.task(name="tasks.identify.regenerate_profile", queue="gpu")
def regenerate_profile(person_id: str, job_id: str = "", use_web: bool = False):
    """Rebuild one person's LLM profile (summary/speech style/topics).

    Queued fire-and-forget after a manual rename so the bio reflects the
    new name instead of whatever identity the LLM inferred from speech.
    With use_web=True, self-hosted SearXNG results for the person's name are
    added as (guarded) context so the bio can reflect their real-world role.
    """
    db = get_session()
    try:
        from tasks.analyze import _load_llm
        tokenizer, model = _load_llm()
        _profile_person(db, person_id, tokenizer, model, job_id, use_web=use_web)
    finally:
        db.close()
