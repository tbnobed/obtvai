"""Orchestrates the full ingestion pipeline for a media asset."""
import os
import math
import subprocess
import json
import uuid
from datetime import datetime
from app import celery_app
from db import get_session
from tasks.base import update_job, append_log, create_job, update_asset


@celery_app.task(bind=True, name="tasks.ingest.run_ingest_pipeline", queue="ingest")
def run_ingest_pipeline(self, media_id: str, job_id: str = None):
    db = get_session()
    try:
        if not job_id:
            job_id = create_job(db, media_id, "ingest")

        update_job(db, job_id, status="running", started_at=datetime.utcnow(), celery_task_id=self.request.id)
        update_asset(db, media_id, status="processing", processing_stage="metadata", processing_progress=5.0)

        from sqlalchemy import text
        row = db.execute(text("SELECT original_path, filename FROM media_assets WHERE id = :mid"), {"mid": media_id}).fetchone()
        if not row or not row[0]:
            raise ValueError("No source file path for asset")

        src_path = row[0]
        append_log(db, job_id, f"Starting ingest for: {src_path}")

        # Direct Curator-proxy ingest: the file IS a Curator web proxy.
        # Pull the hi-res original path from the sidecar metadata XML so
        # NLE exports can relink to the real source.
        from tasks.curator import is_curator_video, find_sidecar_source_path
        if is_curator_video(src_path):
            hires = find_sidecar_source_path(src_path)
            if hires:
                update_asset(db, media_id, source_path=hires)
                append_log(db, job_id, f"Curator proxy ingest — hi-res source from sidecar: {hires}")
            else:
                append_log(db, job_id, "Curator proxy ingest — no hi-res path found in sidecar XML")

        # Extract metadata with ffprobe
        append_log(db, job_id, "Extracting metadata with ffprobe...")
        metadata = _ffprobe(src_path)
        update_asset(db, media_id,
            duration_seconds=metadata.get("duration"),
            width=metadata.get("width"),
            height=metadata.get("height"),
            fps=metadata.get("fps"),
            codec=metadata.get("codec"),
            processing_stage="metadata",
            processing_progress=10.0,
        )
        append_log(db, job_id, f"Metadata: {metadata.get('width')}x{metadata.get('height')} {metadata.get('duration'):.1f}s {metadata.get('codec')}")

        # Create proxy
        append_log(db, job_id, "Creating browser-compatible proxy...")
        proxy_job_id = create_job(db, media_id, "proxy")
        from tasks.proxy import create_proxy
        create_proxy.delay(media_id, proxy_job_id)

        # Extract audio
        append_log(db, job_id, "Queuing audio extraction...")
        audio_job_id = create_job(db, media_id, "audio_extract")
        from tasks.audio import extract_audio
        extract_audio.delay(media_id, audio_job_id)

        # Technical QC
        append_log(db, job_id, "Queuing technical QC...")
        qc_job_id = create_job(db, media_id, "qc")
        from tasks.qc import run_qc
        run_qc.delay(media_id, qc_job_id)

        # Scene detection
        append_log(db, job_id, "Queuing scene detection...")
        scene_job_id = create_job(db, media_id, "scene_detect")
        from tasks.scene_detect import detect_scenes
        detect_scenes.delay(media_id, scene_job_id)

        update_job(db, job_id, status="success", finished_at=datetime.utcnow(), progress=100.0)
        update_asset(db, media_id, processing_stage="queued_for_processing", processing_progress=20.0)
        append_log(db, job_id, "Ingest complete — downstream jobs queued")

    except Exception as e:
        db.rollback()
        update_job(db, job_id or "unknown", status="error", error_message=str(e), finished_at=datetime.utcnow())
        update_asset(db, media_id, status="error", processing_stage="ingest_failed")
        raise
    finally:
        db.close()


VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".mxf", ".ts", ".m2ts", ".wmv", ".flv", ".webm"}
UPLOAD_DIR = "/uploads"


def _sanitize_filename(name: str) -> str:
    """Strip directories, separators, and control chars — the remote server
    controls Content-Disposition, so treat it as hostile."""
    import re
    name = os.path.basename(name.replace("\\", "/")).strip()
    name = re.sub(r"[\x00-\x1f]", "", name)
    name = name.lstrip(".") or "download"
    return name[:200]


def _filename_from_response(resp, url: str) -> str:
    """Best-effort real filename: Content-Disposition, else URL path."""
    import re
    from urllib.parse import urlparse, unquote
    cd = resp.headers.get("content-disposition", "")
    m = re.search(r"filename\*=UTF-8''([^;]+)", cd) or re.search(r'filename="?([^";]+)"?', cd)
    if m:
        return _sanitize_filename(unquote(m.group(1)))
    return _sanitize_filename(unquote(os.path.basename(urlparse(url).path)) or "download")


@celery_app.task(bind=True, name="tasks.ingest.import_from_link", queue="ingest")
def import_from_link(self, media_id: str, url: str, title: str = None):
    """Download a shared link (Dropbox etc.) into /uploads and queue ingest.

    Single video file: becomes this asset. Zip (Dropbox folder link): every
    video inside is extracted; the first becomes this asset, the rest get new
    asset rows, each queued for the normal pipeline.
    """
    import shutil
    import zipfile
    import requests
    from sqlalchemy import text

    db = get_session()
    job_id = None
    tmp_path = os.path.join(UPLOAD_DIR, f".dl_{media_id}")
    try:
        job_id = create_job(db, media_id, "link_import")
        update_job(db, job_id, status="running", started_at=datetime.utcnow(), celery_task_id=self.request.id)
        update_asset(db, media_id, status="processing", processing_stage="downloading", processing_progress=1.0)
        append_log(db, job_id, f"Downloading: {url}")

        os.makedirs(UPLOAD_DIR, exist_ok=True)
        with requests.get(url, stream=True, timeout=(15, 300), allow_redirects=True) as resp:
            resp.raise_for_status()
            fname = _filename_from_response(resp, url)
            total = int(resp.headers.get("content-length") or 0)
            done = 0
            last_pct = -10.0
            with open(tmp_path, "wb") as out:
                for chunk in resp.iter_content(chunk_size=8 * 1024 * 1024):
                    out.write(chunk)
                    done += len(chunk)
                    if total:
                        pct = min(89.0, (done / total) * 90.0)
                        if pct - last_pct >= 5.0:
                            last_pct = pct
                            update_asset(db, media_id, processing_progress=round(pct, 1))
        size = os.path.getsize(tmp_path)
        if size == 0:
            raise RuntimeError("Downloaded file is empty — is the link public?")
        append_log(db, job_id, f"Downloaded {size / 1e6:.1f} MB ({fname})")

        # Zip (Dropbox folder link) vs single file
        is_zip = zipfile.is_zipfile(tmp_path) and os.path.splitext(fname)[1].lower() not in VIDEO_EXTENSIONS
        if is_zip:
            videos = []
            with zipfile.ZipFile(tmp_path) as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    base = os.path.basename(info.filename)
                    if base.startswith(".") or base.startswith("__MACOSX"):
                        continue
                    if os.path.splitext(base)[1].lower() in VIDEO_EXTENSIONS:
                        videos.append((info, base))
                if not videos:
                    raise RuntimeError("The folder link contained no video files")
                append_log(db, job_id, f"Folder link: extracting {len(videos)} video(s)")
                for i, (info, base) in enumerate(videos):
                    vid = media_id if i == 0 else str(uuid.uuid4())
                    dest = os.path.join(UPLOAD_DIR, f"{vid}_{base}")
                    with zf.open(info) as src, open(dest, "wb") as out:
                        shutil.copyfileobj(src, out, 8 * 1024 * 1024)
                    if i == 0:
                        update_asset(db, media_id,
                                     filename=(title or base)[:255],
                                     original_path=dest,
                                     file_size_bytes=os.path.getsize(dest))
                    else:
                        db.execute(
                            text("""
                                INSERT INTO media_assets (id, filename, original_path, status,
                                                          file_size_bytes, created_at)
                                VALUES (:id, :fn, :op, 'pending', :sz, :now)
                            """),
                            {"id": vid, "fn": base[:255], "op": dest,
                             "sz": os.path.getsize(dest), "now": datetime.utcnow()},
                        )
                        db.commit()
                        run_ingest_pipeline.delay(media_id=vid)
            os.remove(tmp_path)
        else:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in VIDEO_EXTENSIONS:
                raise RuntimeError(
                    f"Link is not a video file (got '{fname}'). "
                    "For Dropbox, share a video file or a folder of videos."
                )
            dest = os.path.join(UPLOAD_DIR, f"{media_id}_{fname}")
            shutil.move(tmp_path, dest)
            update_asset(db, media_id,
                         filename=(title or fname)[:255],
                         original_path=dest,
                         file_size_bytes=os.path.getsize(dest))

        update_job(db, job_id, status="success", finished_at=datetime.utcnow(), progress=100.0)
        append_log(db, job_id, "Download complete — starting ingest pipeline")
        update_asset(db, media_id, status="pending", processing_stage="queued_for_processing", processing_progress=0.0)
        run_ingest_pipeline.delay(media_id=media_id)

    except Exception as e:
        db.rollback()
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        if job_id:
            update_job(db, job_id, status="error", error_message=str(e)[:2000], finished_at=datetime.utcnow())
        update_asset(db, media_id, status="error", processing_stage="download_failed")
        raise
    finally:
        db.close()


def _ffprobe(path: str) -> dict:
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_streams", "-show_format", path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr}")
    data = json.loads(result.stdout)

    video_stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    try:
        duration = float(data.get("format", {}).get("duration", 0) or 0)
    except (TypeError, ValueError):
        duration = 0.0
    if not math.isfinite(duration) or duration < 0:
        duration = 0.0
    width = int(video_stream.get("width", 0)) if video_stream else None
    height = int(video_stream.get("height", 0)) if video_stream else None
    codec = video_stream.get("codec_name") if video_stream else None

    fps = None
    if video_stream:
        r_frame_rate = video_stream.get("r_frame_rate", "0/1")
        try:
            num, den = r_frame_rate.split("/")
            fps = float(num) / float(den) if float(den) > 0 else None
        except Exception:
            fps = None

    return {"duration": duration, "width": width, "height": height, "codec": codec, "fps": fps}
