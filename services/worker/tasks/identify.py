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
import uuid
from datetime import datetime
from app import celery_app
from db import get_session
from tasks.base import update_job, append_log

VOICE_SIM_THRESHOLD = 0.60
FACE_SIM_THRESHOLD = 0.60
FACE_ATTACH_OVERLAP = 0.25
_PROFILE_CHARS = 12000


def _cosine(a, b) -> float:
    import numpy as np
    va, vb = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    na, nb = np.linalg.norm(va), np.linalg.norm(vb)
    if na == 0 or nb == 0:
        return -1.0
    return float(np.dot(va, vb) / (na * nb))


def _blend(old, new):
    """Running average of two embeddings, renormalized."""
    import numpy as np
    if old is None:
        return [float(x) for x in new]
    v = (np.asarray(old, dtype=float) + np.asarray(new, dtype=float)) / 2.0
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


def _profile_person(db, person_id: str, tokenizer, model, job_id: str):
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
    prompt = (
        f"The following are things {display_name} has said across a video library.\n"
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

        for spk, segs, secs, first_at in speaker_stats:
            voice = voice_map.get(spk)
            cluster = cluster_for_speaker.get(spk)
            face = cluster[1] if cluster else None

            match = None
            best_sim = 0.0
            for p in people:
                sim = -1.0
                if voice and p[3]:
                    sim = _cosine(voice, p[3])
                    threshold = VOICE_SIM_THRESHOLD
                elif face and p[4]:
                    sim = _cosine(face, p[4])
                    threshold = FACE_SIM_THRESHOLD
                else:
                    continue
                if sim >= threshold and sim > best_sim:
                    best_sim, match = sim, p

            if match is None and face:
                for p in people:
                    if p[4]:
                        sim = _cosine(face, p[4])
                        if sim >= FACE_SIM_THRESHOLD and sim > best_sim:
                            best_sim, match = sim, p

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
                new_voice = _blend(match[3], voice) if voice else match[3]
                new_face = _blend(match[4], face) if face else match[4]
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

        # Face-only clusters (people seen but never speaking): match against
        # known faces; never create new people from faces alone (too noisy).
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

        # Drop people that no longer have any appearances (stale from re-runs)
        db.execute(text("DELETE FROM people WHERE id NOT IN (SELECT DISTINCT person_id FROM person_appearances)"))
        db.commit()

        # ── AI profiles for everyone touched ────────────────────────────────
        touched = list(dict.fromkeys(touched))
        if touched:
            update_job(db, job_id, progress=60.0)
            append_log(db, job_id, f"Generating AI profiles for {len(touched)} people...")
            tok, mdl = _ensure_llm()
            for pid in touched:
                _profile_person(db, pid, tok, mdl, job_id)

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
