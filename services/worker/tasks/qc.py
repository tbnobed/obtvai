"""Technical QC pass: audio clipping, silence, and black-frame detection via ffmpeg."""
import re
import subprocess
from datetime import datetime
from app import celery_app
from db import get_session
from tasks.base import update_job, append_log

EDITORIAL_FLAGS = ("flash_frames", "short_shots", "typos", "similar_shots")


@celery_app.task(bind=True, name="tasks.qc.run_qc", queue="cpu")
def run_qc(self, media_id: str, job_id: str = None):
    db = get_session()
    try:
        update_job(db, job_id, status="running", started_at=datetime.utcnow(), celery_task_id=self.request.id)

        from sqlalchemy import text
        row = db.execute(
            text("SELECT original_path, duration_seconds FROM media_assets WHERE id = :mid"),
            {"mid": media_id},
        ).fetchone()
        if not row or not row[0]:
            raise ValueError("No source file path for asset")
        src_path = row[0]
        duration = float(row[1] or 0)

        append_log(db, job_id, f"Running technical QC on: {src_path}")
        update_job(db, job_id, progress=10.0)

        flags = []
        qc = {"flags": flags}

        # ── Audio analysis (volumedetect) ────────────────────────────────
        # Curator proxies are video-only; their audio lives in sidecar
        # _audioN.mp4 files next to the video. Analyze those instead so the
        # asset isn't falsely flagged no_audio.
        audio_paths = [src_path]
        from tasks.curator import is_curator_video, has_audio_stream, find_curator_audio
        if is_curator_video(src_path) and not has_audio_stream(src_path):
            sidecars = find_curator_audio(src_path)
            if sidecars:
                audio_paths = sidecars
                append_log(db, job_id, f"Video-only Curator proxy — analyzing sidecar audio: "
                                       f"{[s.split('/')[-1] for s in sidecars]}")

        append_log(db, job_id, "Analyzing audio levels (volumedetect)...")
        max_vol = None
        mean_vol = None
        for ap in audio_paths:
            audio_out = _run_ffmpeg_filter(ap, ["-af", "volumedetect", "-vn"])
            mv = _grep_float(audio_out, r"max_volume:\s*(-?[\d.]+)\s*dB")
            av = _grep_float(audio_out, r"mean_volume:\s*(-?[\d.]+)\s*dB")
            if mv is not None and (max_vol is None or mv > max_vol):
                max_vol = mv
            if av is not None and (mean_vol is None or av > mean_vol):
                mean_vol = av
        has_audio = max_vol is not None
        qc["max_volume_db"] = max_vol
        qc["mean_volume_db"] = mean_vol

        if not has_audio:
            flags.append("no_audio")
        else:
            if max_vol >= -0.1:
                flags.append("audio_clipping")
            if mean_vol is not None and mean_vol < -50.0:
                flags.append("audio_silent")
            elif mean_vol is not None and mean_vol < -35.0:
                flags.append("audio_low")
        update_job(db, job_id, progress=50.0)

        # ── Black frame detection ────────────────────────────────────────
        append_log(db, job_id, "Detecting black segments (blackdetect)...")
        black_out = _run_ffmpeg_filter(src_path, ["-vf", "blackdetect=d=1.0:pix_th=0.10", "-an"])
        black_segments = []
        for m in re.finditer(r"black_start:([\d.]+)\s+black_end:([\d.]+)\s+black_duration:([\d.]+)", black_out):
            black_segments.append({
                "start": round(float(m.group(1)), 2),
                "end": round(float(m.group(2)), 2),
                "duration": round(float(m.group(3)), 2),
            })
        total_black = sum(s["duration"] for s in black_segments)
        qc["black_segments"] = black_segments[:50]
        qc["black_seconds"] = round(total_black, 2)
        if black_segments:
            flags.append("black_frames")
        if duration > 0 and total_black / duration > 0.9:
            flags.append("mostly_black")

        append_log(db, job_id, f"QC flags: {flags or ['clean']}")
        import json
        # Technical and editorial QC can overlap — serialize the read-modify-
        # write on qc_flags and preserve the other pass's keys/flags.
        db.execute(text("SELECT pg_advisory_xact_lock(hashtext('obtv_qc:' || :mid))"), {"mid": media_id})
        cur_row = db.execute(text("SELECT qc_flags FROM media_assets WHERE id = :mid"), {"mid": media_id}).fetchone()
        current = dict((cur_row[0] if cur_row else None) or {})
        editorial_flags = [f for f in (current.get("flags") or []) if f in EDITORIAL_FLAGS]
        merged = {**current, **qc}
        merged["flags"] = flags + editorial_flags
        db.execute(
            text("UPDATE media_assets SET qc_flags = CAST(:qc AS jsonb) WHERE id = :mid"),
            {"qc": json.dumps(merged), "mid": media_id},
        )
        db.commit()
        update_job(db, job_id, status="success", finished_at=datetime.utcnow(), progress=100.0)

    except Exception as e:
        db.rollback()
        update_job(db, job_id or "unknown", status="error", error_message=str(e), finished_at=datetime.utcnow())
        raise
    finally:
        db.close()


@celery_app.task(bind=True, name="tasks.qc.run_editorial_qc", queue="cpu")
def run_editorial_qc(self, media_id: str, job_id: str = None):
    """Editorial QC: flash frames, short shots, transcript typos, and
    too-similar adjacent shots. Runs after scenes + transcript exist and
    merges its results into media_assets.qc_flags."""
    import os
    import json
    db = get_session()
    try:
        update_job(db, job_id, status="running", started_at=datetime.utcnow(), celery_task_id=self.request.id)

        from sqlalchemy import text
        row = db.execute(
            text("SELECT original_path, proxy_path, duration_seconds, fps, qc_flags FROM media_assets WHERE id = :mid"),
            {"mid": media_id},
        ).fetchone()
        if not row:
            raise ValueError("Asset not found")
        video_path = row[1] if (row[1] and os.path.exists(row[1])) else row[0]
        if not video_path or not os.path.exists(video_path):
            raise ValueError("No readable video file for editorial QC")
        duration = float(row[2] or 0)
        fps = float(row[3] or 0) or 30.0
        qc = {}          # editorial keys only — merged under lock at write time
        ed_flags = []
        notes = []

        flash_max_frames = int(os.getenv("QC_FLASH_MAX_FRAMES", "4"))
        short_shot_secs = float(os.getenv("QC_SHORT_SHOT_SECONDS", "2.0"))
        cut_threshold = float(os.getenv("QC_CUT_THRESHOLD", "0.30"))
        similar_threshold = float(os.getenv("QC_SIMILAR_SHOT_THRESHOLD", "0.90"))

        # ── Cut list (frame-accurate, independent of PySceneDetect's minimum
        # scene length so 1-4 frame flashes are not swallowed) ──────────────
        append_log(db, job_id, f"Detecting cuts (scene>{cut_threshold}) for flash/short-shot checks...")
        out = _run_ffmpeg_filter(video_path, ["-vf", f"select='gt(scene,{cut_threshold})',showinfo", "-an"])
        cuts = sorted({float(m.group(1)) for m in re.finditer(r"pts_time:([\d.]+)", out)})
        bounds = [0.0] + cuts
        if duration > bounds[-1]:
            bounds.append(duration)
        shots = []
        for i in range(len(bounds) - 1):
            s, e = bounds[i], bounds[i + 1]
            if e - s <= 0:
                continue
            shots.append({"start": round(s, 3), "end": round(e, 3),
                          "frames": max(1, round((e - s) * fps))})

        flash_frames = [sh for sh in shots if sh["frames"] <= flash_max_frames]
        short_shots = [sh for sh in shots
                       if sh["frames"] > flash_max_frames and (sh["end"] - sh["start"]) < short_shot_secs]
        qc["flash_frames"] = flash_frames[:100]
        qc["short_shots"] = short_shots[:100]
        if flash_frames:
            ed_flags.append("flash_frames")
        if short_shots:
            ed_flags.append("short_shots")
        append_log(db, job_id, f"{len(shots)} shots — {len(flash_frames)} flash, {len(short_shots)} short (<{short_shot_secs}s)")
        update_job(db, job_id, progress=40.0)

        scenes = db.execute(
            text("SELECT id, start_time, end_time, thumbnail_url FROM scenes WHERE media_id = :mid ORDER BY start_time"),
            {"mid": media_id},
        ).fetchall()

        # ── Typos in on-screen text (OCR of scene keyframes) ─────────────
        typos = []
        thumbs = []
        from config import THUMBNAILS_DIR
        for s in scenes:
            if s[3]:
                tf = os.path.join(THUMBNAILS_DIR, os.path.basename(s[3]))
                if os.path.exists(tf):
                    thumbs.append((float(s[1]), tf))
        if not thumbs:
            notes.append("No scene keyframes — on-screen typo check skipped")
        else:
            ocr_lines = []  # (scene start, text)
            try:
                append_log(db, job_id, f"Running OCR on {len(thumbs)} scene keyframes...")
                import easyocr
                reader = easyocr.Reader(
                    ["en"], gpu=False, verbose=False,
                    model_storage_directory="/root/.cache/easyocr",
                )
                ocr_min_conf = float(os.getenv("QC_OCR_MIN_CONFIDENCE", "0.5"))
                for si, (start_t, tf) in enumerate(thumbs):
                    try:
                        # mag_ratio upscales small lower-third text before
                        # recognition — cuts letter-drop misreads markedly.
                        results = reader.readtext(tf, detail=1, paragraph=False, mag_ratio=1.5)
                    except Exception as fe:
                        append_log(db, job_id, f"OCR failed on frame @{start_t:.1f}s: {fe}")
                        continue
                    texts = [t for (_box, t, conf) in results
                             if conf >= ocr_min_conf and t and t.strip()]
                    if texts:
                        ocr_lines.append((start_t, " | ".join(t.strip() for t in texts)[:500]))
                    if si % 10 == 0:
                        update_job(db, job_id, progress=40.0 + 20.0 * (si + 1) / len(thumbs))
            except Exception as e:
                append_log(db, job_id, f"OCR unavailable: {e}")
                notes.append(f"OCR unavailable — on-screen typo check skipped: {str(e)[:120]}")
                ocr_lines = None

            if ocr_lines is None:
                pass
            elif not ocr_lines:
                append_log(db, job_id, "No on-screen text detected")
            else:
                from tasks.llm_remote import remote_enabled, remote_chat
                if not remote_enabled():
                    notes.append("Remote LLM not configured (LLM_BASE_URL) — on-screen typo check skipped")
                else:
                    append_log(db, job_id, f"Checking on-screen text from {len(ocr_lines)} frames for misspellings...")
                    lines = [f"{i}|{t}" for i, (_st, t) in enumerate(ocr_lines)]
                    # Chunk so long text never blows the prompt budget; every
                    # line is sent exactly once (no break-and-drop).
                    chunk, chunks, size = [], [], 0
                    for ln in lines:
                        if size + len(ln) > 6000 and chunk:
                            chunks.append(chunk)
                            chunk, size = [], 0
                        chunk.append(ln)
                        size += len(ln) + 1
                    if chunk:
                        chunks.append(chunk)
                    for ci, ch in enumerate(chunks):
                        prompt = (
                            "You are a broadcast QC proofreader checking on-screen graphics. "
                            "Each line below is `index|text` — OCR output of text visible in "
                            "video frames (segments separated by ' | '). List genuine English "
                            "misspellings only. Ignore proper nouns, names, brands, acronyms, "
                            "stylized casing, punctuation, grammar, and OCR artifacts. "
                            "OCR frequently drops or substitutes single letters (WHITE→WHTE, "
                            "HOUSE→HUUSE) — these are NOT typos. If the correctly spelled "
                            "version of the word or phrase also appears anywhere in the same "
                            "line, it is OCR noise: skip it. Only report a word a viewer "
                            "would actually see misspelled in the graphic. Reply with "
                            'ONLY a JSON array like [{"line": 3, "word": "recieve", '
                            '"suggestion": "receive"}]. Reply [] if none.\n\n' + "\n".join(ch)
                        )
                        try:
                            resp = remote_chat([{"role": "user", "content": prompt}], max_new_tokens=1024)
                            m = re.search(r"\[.*\]", resp, re.DOTALL)
                            for item in (json.loads(m.group(0)) if m else []):
                                idx = int(item.get("line", -1))
                                if not (0 <= idx < len(ocr_lines) and item.get("word")):
                                    continue
                                word = str(item["word"])[:80]
                                sugg = str(item.get("suggestion") or "")[:80]
                                line_text = ocr_lines[idx][1]
                                # OCR-misread guard: if the corrected word is
                                # also present in the same frame's text, the
                                # "typo" is a garbled duplicate read.
                                if sugg and sugg.lower() in line_text.lower():
                                    continue
                                typos.append({
                                    "time": round(ocr_lines[idx][0], 2),
                                    "word": word,
                                    "suggestion": sugg,
                                    "context": line_text[:160],
                                })
                        except Exception as e:
                            append_log(db, job_id, f"Typo check chunk {ci + 1}/{len(chunks)} failed: {e}")
                            notes.append(f"On-screen typo check incomplete: {str(e)[:160]}")
                        update_job(db, job_id, progress=60.0 + 15.0 * (ci + 1) / max(1, len(chunks)))
        # The same graphic persists across many scenes — report each
        # misspelling once (first occurrence).
        seen = set()
        deduped = []
        for t in typos:
            key = (t["word"].lower(), t["suggestion"].lower())
            if key in seen:
                continue
            seen.add(key)
            deduped.append(t)
        typos = deduped
        qc["typos"] = typos[:100]
        if typos:
            ed_flags.append("typos")

        # ── Too-similar adjacent shots (wide → jib etc.) ─────────────────
        similar = []
        if len(scenes) < 2:
            notes.append("Fewer than 2 scenes — similar-shot check skipped")
        else:
            try:
                import uuid as _uuid
                from tasks.qdrant_util import get_qdrant
                qdrant = get_qdrant()
                ids = [str(_uuid.uuid5(_uuid.NAMESPACE_DNS, s[0])) for s in scenes]
                points = qdrant.retrieve(collection_name="scenes", ids=ids, with_vectors=True)
                vecs = {p.id: p.vector for p in points if p.vector}
                missing = sum(1 for pid in ids if pid not in vecs)
                if missing:
                    notes.append(f"{missing}/{len(scenes)} scenes have no visual embedding yet "
                                 f"(run Visual Embed, then re-run QC)")
                for i in range(len(scenes) - 1):
                    va, vb = vecs.get(ids[i]), vecs.get(ids[i + 1])
                    if not va or not vb:
                        continue
                    dot = sum(a * b for a, b in zip(va, vb))
                    na = sum(a * a for a in va) ** 0.5
                    nb = sum(b * b for b in vb) ** 0.5
                    sim = dot / (na * nb) if na and nb else 0.0
                    if sim >= similar_threshold:
                        similar.append({
                            "a_start": round(float(scenes[i][1]), 2),
                            "b_start": round(float(scenes[i + 1][1]), 2),
                            "a_scene_id": scenes[i][0],
                            "b_scene_id": scenes[i + 1][0],
                            "similarity": round(sim, 3),
                        })
            except Exception as e:
                append_log(db, job_id, f"Similar-shot check failed: {e}")
                notes.append(f"Similar-shot check failed: {str(e)[:160]}")
        qc["similar_shots"] = similar[:100]
        if similar:
            ed_flags.append("similar_shots")

        qc["editorial_notes"] = notes
        qc["editorial_checked_at"] = datetime.utcnow().isoformat() + "Z"
        append_log(db, job_id, f"Editorial QC: {len(flash_frames)} flash, {len(short_shots)} short, "
                               f"{len(typos)} typos, {len(similar)} similar pairs")
        # Serialize against the technical QC pass and preserve its keys/flags.
        db.execute(text("SELECT pg_advisory_xact_lock(hashtext('obtv_qc:' || :mid))"), {"mid": media_id})
        cur_row = db.execute(text("SELECT qc_flags FROM media_assets WHERE id = :mid"), {"mid": media_id}).fetchone()
        current = dict((cur_row[0] if cur_row else None) or {})
        tech_flags = [f for f in (current.get("flags") or []) if f not in EDITORIAL_FLAGS]
        merged = {**current, **qc}
        merged["flags"] = tech_flags + ed_flags
        db.execute(
            text("UPDATE media_assets SET qc_flags = CAST(:qc AS jsonb) WHERE id = :mid"),
            {"qc": json.dumps(merged), "mid": media_id},
        )
        db.commit()
        update_job(db, job_id, status="success", finished_at=datetime.utcnow(), progress=100.0)

    except Exception as e:
        db.rollback()
        update_job(db, job_id or "unknown", status="error", error_message=str(e), finished_at=datetime.utcnow())
        raise
    finally:
        db.close()


def maybe_queue_editorial_qc(db, media_id: str) -> bool:
    """Queue editorial QC once BOTH prerequisites are terminal: the transcript
    path (transcribe/diarize/index) and visual embedding. Called from the end
    of build_index and embed_scenes — whichever finishes last queues the job.
    Callers must mark their own job terminal before calling."""
    from sqlalchemy import text
    # Serialize the check+enqueue so two finishers can't both queue.
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext('obtv_qc_queue:' || :mid))"), {"mid": media_id})
    busy = db.execute(
        text("SELECT count(*) FROM processing_jobs WHERE media_id = :mid "
             "AND status IN ('pending','running') "
             "AND job_type IN ('transcribe','diarize','index','scene_detect','visual_embed','qc_editorial')"),
        {"mid": media_id},
    ).scalar()
    if busy:
        db.commit()  # release the advisory lock
        return False
    from tasks.base import create_job
    jid = create_job(db, media_id, "qc_editorial")
    run_editorial_qc.delay(media_id, jid)
    return True


def _run_ffmpeg_filter(path: str, filter_args: list) -> str:
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-i", path, *filter_args, "-f", "null", "-"]
    result = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=1800
    )
    return result.stdout or ""


def _grep_float(text: str, pattern: str):
    m = re.search(pattern, text)
    return float(m.group(1)) if m else None
