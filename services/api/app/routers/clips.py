import uuid
import csv
import json
import io
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from ..database import get_db
from ..models import ClipList, Clip, MediaAsset, Scene
from .projects import touch_project
from ..schemas import (
    ClipListOut, ClipOut, ClipListInput, ClipListUpdate,
    ClipExportInput, ClipExportResult,
    RenderPresetInput, RenderJobOut,
    RoughCutInput, ReelJobOut,
)

_FPS = 25


def _path_map() -> list[tuple[str, str]]:
    """Parse EXPORT_PATH_MAP, e.g. '/media=V:\\Media;/media2=\\\\nas\\media2'.

    Translates server-side mount paths into the paths edit workstations see,
    so Premiere/Resolve relink straight to the hi-res originals.
    """
    import os as _os
    pairs = []
    for part in _os.getenv("EXPORT_PATH_MAP", "").split(";"):
        if "=" in part:
            src, dst = part.split("=", 1)
            if src.strip():
                pairs.append((src.strip(), dst.strip()))
    pairs.sort(key=lambda p: -len(p[0]))
    return pairs


def _translate(path: str) -> str:
    for src, dst in _path_map():
        # Boundary-safe prefix match: /media must not remap /media_archive
        if path == src or (path.startswith(src) and path[len(src)] in ("/", "\\")):
            mapped = dst + path[len(src):]
            if "\\" in dst:
                mapped = mapped.replace("/", "\\")
            return mapped
    return path


def _file_url(path: str) -> str:
    p = path.replace("\\", "/")
    if p.startswith("//"):
        return "file:" + p            # UNC \\nas\share -> file://nas/share
    if p.startswith("/"):
        return "file://" + p          # POSIX /mnt/media/x -> file:///mnt/...
    return "file:///" + p             # V:/Media/x -> file:///V:/Media/x


def _rational(seconds: float) -> str:
    """FCPXML rational time at 25fps, e.g. 253/25s."""
    return f"{int(round(seconds * _FPS))}/{_FPS}s"


def _fcpxml(name: str, clips, paths: dict[str, str] | None = None) -> str:
    from xml.sax.saxutils import escape, quoteattr
    paths = paths or {}
    assets = {}
    for c in clips:
        if c.media_id not in assets:
            assets[c.media_id] = c.filename or c.media_id
    resources = ['    <format id="r1" name="FFVideoFormat1080p25" frameDuration="1/25s" width="1920" height="1080"/>']
    asset_ids = {}
    for i, (mid, fname) in enumerate(assets.items(), 2):
        rid = f"r{i}"
        asset_ids[mid] = rid
        src_path = _translate(paths.get(mid) or fname)
        resources.append(
            f'    <asset id={quoteattr(rid)} name={quoteattr(fname)} start="0s" hasVideo="1" hasAudio="1" format="r1">\n'
            f'      <media-rep kind="original-media" src={quoteattr(_file_url(src_path))}/>\n'
            f'    </asset>'
        )
    offset = 0.0
    spine = []
    for c in clips:
        dur = max(0.04, c.end_time - c.start_time)
        label = c.label or c.filename or "clip"
        spine.append(
            f'          <asset-clip ref={quoteattr(asset_ids[c.media_id])} name={quoteattr(label)} '
            f'offset={quoteattr(_rational(offset))} start={quoteattr(_rational(c.start_time))} '
            f'duration={quoteattr(_rational(dur))} format="r1"/>'
        )
        offset += dur
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE fcpxml>\n'
        '<fcpxml version="1.9">\n'
        '  <resources>\n' + "\n".join(resources) + "\n  </resources>\n"
        f'  <library>\n    <event name={quoteattr(escape(name))}>\n'
        f'      <project name={quoteattr(escape(name))}>\n'
        f'        <sequence format="r1" duration={quoteattr(_rational(offset))}>\n'
        '          <spine>\n' + "\n".join(f"  {s}" for s in spine) + "\n          </spine>\n"
        '        </sequence>\n      </project>\n    </event>\n  </library>\n'
        '</fcpxml>\n'
    )


def _xmeml_rate(fps_val: float) -> tuple[int, str, str]:
    """Return (timebase, actual fps used for frame math, <rate> element).

    xmeml timebase is an integer; fractional NTSC rates (29.97, 23.976, 59.94)
    are expressed as the rounded timebase with ntsc=TRUE."""
    fps_val = float(fps_val or 0) or float(_FPS)
    tb = int(round(fps_val))
    ntsc = "TRUE" if abs(fps_val - tb) > 0.01 else "FALSE"
    rate = f"<rate><timebase>{tb}</timebase><ntsc>{ntsc}</ntsc></rate>"
    return tb, ntsc, rate


_SEQ_W, _SEQ_H = 1920, 1080


def _xmeml_scale_filter(w: int, h: int) -> str:
    """Basic Motion scale so a clip fills the sequence frame (fit-inside).

    Premiere doesn't round-trip the "Scale to Frame Size" flag through FCP7
    XML, so we bake the equivalent Motion > Scale value instead."""
    if not w or not h:
        return ""
    pct = round(min(_SEQ_W / w, _SEQ_H / h) * 100, 2)
    if abs(pct - 100.0) < 0.01:
        return ""
    return (
        '<filter><effect><name>Basic Motion</name><effectid>basic</effectid>'
        '<effectcategory>motion</effectcategory><effecttype>motion</effecttype>'
        '<mediatype>video</mediatype>'
        '<parameter authoringApp="PremierePro"><parameterid>scale</parameterid>'
        '<name>Scale</name><valuemin>0</valuemin><valuemax>1000</valuemax>'
        f'<value>{pct}</value></parameter>'
        '</effect></filter>'
    )


def _xmeml(name: str, clips, paths: dict[str, str] | None = None,
           lognotes: dict[str, str] | None = None,
           fps_map: dict[str, float] | None = None,
           dims_map: dict[str, tuple[int, int]] | None = None) -> str:
    """Premiere Pro XML (FCP7 xmeml v4) — "Export for Curator".

    Curator's Premiere panel matches assets by reading the clip's Log Note
    field, so each clipitem carries <logginginfo><lognote> = "assetId=<id>"
    for the Curator asset linked to that media (blank when unlinked).
    Each file/clipitem uses its own asset's frame rate; the sequence uses
    the first clip's rate."""
    from xml.sax.saxutils import escape
    paths = paths or {}
    lognotes = lognotes or {}
    fps_map = fps_map or {}
    dims_map = dims_map or {}

    def clip_fps(media_id: str) -> float:
        return float(fps_map.get(media_id) or 0) or float(_FPS)

    seq_fps = clip_fps(clips[0].media_id) if clips else float(_FPS)
    _, _, seq_rate = _xmeml_rate(seq_fps)

    def fr(seconds: float, fps_val: float) -> int:
        return int(round(seconds * fps_val))

    file_ids: dict[str, str] = {}
    items = []
    rec = 0.0
    for i, c in enumerate(clips, 1):
        dur = max(0.04, c.end_time - c.start_time)
        label = escape(c.label or c.filename or "clip")
        fname = escape(c.filename or c.media_id)
        _aid = lognotes.get(c.media_id) or ""
        lognote = escape(f"assetId={_aid}" if _aid else "")
        fps_val = clip_fps(c.media_id)
        _, _, rate = _xmeml_rate(fps_val)
        w, h = dims_map.get(c.media_id) or (0, 0)
        scale_filter = _xmeml_scale_filter(w, h)
        if c.media_id in file_ids:
            file_el = f'<file id="{file_ids[c.media_id]}"/>'
        else:
            fid = f"file-{len(file_ids) + 1}"
            file_ids[c.media_id] = fid
            src = _translate(paths.get(c.media_id) or c.filename or c.media_id)
            file_el = (
                f'<file id="{fid}"><name>{fname}</name>'
                f'<pathurl>{escape(_file_url(src))}</pathurl>{rate}'
                f'<media><video><samplecharacteristics>{rate}'
                f'<width>{w or _SEQ_W}</width><height>{h or _SEQ_H}</height>'
                f'</samplecharacteristics></video><audio/></media></file>'
            )
        items.append(
            f'        <clipitem id="clipitem-{i}">\n'
            f'          <name>{label}</name>\n'
            f'          {rate}\n'
            f'          <start>{fr(rec, seq_fps)}</start><end>{fr(rec + dur, seq_fps)}</end>\n'
            f'          <in>{fr(c.start_time, fps_val)}</in><out>{fr(c.end_time, fps_val)}</out>\n'
            f'          {file_el}\n'
            + (f'          {scale_filter}\n' if scale_filter else '')
            + f'          <logginginfo><lognote>{lognote}</lognote></logginginfo>\n'
            f'        </clipitem>'
        )
        rec += dur
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE xmeml>\n'
        '<xmeml version="4">\n'
        '<sequence id="sequence-1">\n'
        f'  <name>{escape(name)}</name>\n'
        f'  {seq_rate}\n'
        f'  <duration>{fr(rec, seq_fps)}</duration>\n'
        '  <media>\n'
        '    <video>\n'
        f'      <format><samplecharacteristics>{seq_rate}'
        f'<width>{_SEQ_W}</width><height>{_SEQ_H}</height></samplecharacteristics></format>\n'
        '      <track>\n' + "\n".join(items) + '\n'
        '      </track>\n'
        '    </video>\n'
        '    <audio/>\n'
        '  </media>\n'
        '</sequence>\n'
        '</xmeml>\n'
    )


def _otio(name: str, clips, paths: dict[str, str] | None = None) -> str:
    paths = paths or {}
    def rt(seconds: float) -> dict:
        return {
            "OTIO_SCHEMA": "RationalTime.1",
            "rate": float(_FPS),
            "value": round(seconds * _FPS, 3),
        }

    children = []
    for c in clips:
        children.append({
            "OTIO_SCHEMA": "Clip.2",
            "name": c.label or c.filename or "clip",
            "source_range": {
                "OTIO_SCHEMA": "TimeRange.1",
                "start_time": rt(c.start_time),
                "duration": rt(max(0.04, c.end_time - c.start_time)),
            },
            "media_references": {
                "DEFAULT_MEDIA": {
                    "OTIO_SCHEMA": "ExternalReference.1",
                    "target_url": _translate(paths.get(c.media_id) or c.filename or c.media_id),
                }
            },
            "active_media_reference_key": "DEFAULT_MEDIA",
        })
    timeline = {
        "OTIO_SCHEMA": "Timeline.1",
        "name": name,
        "global_start_time": rt(0),
        "tracks": {
            "OTIO_SCHEMA": "Stack.1",
            "name": "tracks",
            "children": [{
                "OTIO_SCHEMA": "Track.1",
                "name": "V1",
                "kind": "Video",
                "children": children,
            }],
        },
    }
    return json.dumps(timeline, indent=2)

router = APIRouter(prefix="/clips", tags=["clips"])


async def _load_clip_list(id: str, db: AsyncSession) -> ClipList:
    result = await db.execute(
        select(ClipList).where(ClipList.id == id)
    )
    cl = result.scalar_one_or_none()
    if not cl:
        raise HTTPException(status_code=404, detail="Clip list not found")
    return cl


async def _build_clip_out(clip: Clip, db: AsyncSession) -> ClipOut:
    asset = (await db.execute(select(MediaAsset).where(MediaAsset.id == clip.media_id))).scalar_one_or_none()
    scene = (await db.execute(
        select(Scene)
        .where(Scene.media_id == clip.media_id, Scene.start_time <= clip.start_time)
        .order_by(desc(Scene.start_time))
        .limit(1)
    )).scalar_one_or_none()
    thumbnail_url = (scene.thumbnail_url if scene else None) or (asset.thumbnail_url if asset else None)
    return ClipOut(
        id=clip.id,
        media_id=clip.media_id,
        filename=asset.filename if asset else None,
        start_time=clip.start_time,
        end_time=clip.end_time,
        label=clip.label,
        notes=clip.notes,
        approved=clip.approved or False,
        match_reason=clip.match_reason,
        thumbnail_url=thumbnail_url,
    )


async def _build_clip_list_out(cl: ClipList, db: AsyncSession) -> ClipListOut:
    clips_q = await db.execute(
        select(Clip).where(Clip.clip_list_id == cl.id).order_by(Clip.position)
    )
    clips = clips_q.scalars().all()
    clip_outs = [await _build_clip_out(c, db) for c in clips]
    return ClipListOut(
        id=cl.id,
        name=cl.name,
        description=cl.description,
        project_id=cl.project_id,
        locked=cl.locked,
        created_at=cl.created_at,
        clips=clip_outs,
    )


@router.get("", response_model=list[ClipListOut])
async def list_clip_lists(project_id: str | None = None, db: AsyncSession = Depends(get_db)):
    q = select(ClipList).order_by(desc(ClipList.created_at))
    if project_id:
        q = q.where(ClipList.project_id == project_id)
    result = await db.execute(q)
    cls = result.scalars().all()
    return [await _build_clip_list_out(cl, db) for cl in cls]


@router.post("", response_model=ClipListOut, status_code=201)
async def create_clip_list(body: ClipListInput, db: AsyncSession = Depends(get_db)):
    cl = ClipList(
        id=str(uuid.uuid4()),
        name=body.name,
        description=body.description,
        project_id=body.project_id,
        created_at=datetime.utcnow(),
    )
    db.add(cl)
    await db.flush()

    for i, c in enumerate(body.clips or []):
        clip = Clip(
            id=str(uuid.uuid4()),
            clip_list_id=cl.id,
            media_id=c.media_id,
            start_time=c.start_time,
            end_time=c.end_time,
            label=c.label,
            notes=c.notes,
            approved=c.approved,
            match_reason=c.match_reason,
            position=i,
        )
        db.add(clip)

    await touch_project(db, cl.project_id)
    await db.commit()
    await db.refresh(cl)
    return await _build_clip_list_out(cl, db)


@router.get("/{id}", response_model=ClipListOut)
async def get_clip_list(id: str, db: AsyncSession = Depends(get_db)):
    cl = await _load_clip_list(id, db)
    return await _build_clip_list_out(cl, db)


@router.patch("/{id}", response_model=ClipListOut)
async def update_clip_list(id: str, body: ClipListUpdate, db: AsyncSession = Depends(get_db)):
    cl = await _load_clip_list(id, db)
    if "locked" in body.model_fields_set and body.locked is not None:
        cl.locked = body.locked
    mutating = (
        body.name is not None
        or body.description is not None
        or "project_id" in body.model_fields_set
        or body.clips is not None
    )
    if cl.locked and mutating and not ("locked" in body.model_fields_set and body.locked is False):
        raise HTTPException(423, "Clip list is picture-locked. Unlock it to make changes.")
    if body.name is not None:
        cl.name = body.name
    if body.description is not None:
        cl.description = body.description
    if "project_id" in body.model_fields_set:
        cl.project_id = body.project_id
    if body.clips is not None:
        existing_q = await db.execute(select(Clip).where(Clip.clip_list_id == cl.id))
        for c in existing_q.scalars().all():
            await db.delete(c)
        for i, c in enumerate(body.clips):
            clip = Clip(
                id=str(uuid.uuid4()),
                clip_list_id=cl.id,
                media_id=c.media_id,
                start_time=c.start_time,
                end_time=c.end_time,
                label=c.label,
                notes=c.notes,
                approved=c.approved,
                match_reason=c.match_reason,
                position=i,
            )
            db.add(clip)
    await touch_project(db, cl.project_id)
    await db.commit()
    await db.refresh(cl)
    return await _build_clip_list_out(cl, db)


@router.delete("/{id}", status_code=204)
async def delete_clip_list(id: str, db: AsyncSession = Depends(get_db)):
    cl = await _load_clip_list(id, db)
    if cl.locked:
        raise HTTPException(423, "Clip list is picture-locked. Unlock it to delete.")
    await db.delete(cl)
    await db.commit()


@router.post("/{id}/export", response_model=ClipExportResult)
async def export_clip_list(id: str, body: ClipExportInput, db: AsyncSession = Depends(get_db)):
    cl = await _load_clip_list(id, db)
    cl_out = await _build_clip_list_out(cl, db)

    fmt = body.format.lower()
    if fmt not in ("edl", "csv", "json", "fcpxml", "otio", "xmeml"):
        raise HTTPException(status_code=400, detail="Format must be edl, csv, json, fcpxml, otio, or xmeml")

    # Map media_id -> original hi-res path so exports relink to source media
    media_ids = {c.media_id for c in cl_out.clips}
    paths: dict[str, str] = {}
    lognotes: dict[str, str] = {}
    fps_map: dict[str, float] = {}
    dims_map: dict[str, tuple[int, int]] = {}
    if media_ids:
        rows = await db.execute(
            select(MediaAsset.id, MediaAsset.original_path, MediaAsset.source_path,
                   MediaAsset.curator_asset_id, MediaAsset.fps,
                   MediaAsset.width, MediaAsset.height)
            .where(MediaAsset.id.in_(media_ids))
        )
        for mid, op, sp, cid, fps_v, w_v, h_v in rows.all():
            # source_path (hi-res original from Curator sidecar metadata) wins
            # over original_path — for Curator-direct ingests original_path IS
            # the proxy.
            if sp or op:
                paths[mid] = sp or op
            if cid:
                lognotes[mid] = cid
            if fps_v:
                fps_map[mid] = float(fps_v)
            if w_v and h_v:
                dims_map[mid] = (int(w_v), int(h_v))

    if fmt == "xmeml":
        content = _xmeml(cl_out.name, cl_out.clips, paths, lognotes, fps_map, dims_map)
        filename = f"{cl_out.name.replace(' ', '_')}.xml"

    elif fmt == "fcpxml":
        content = _fcpxml(cl_out.name, cl_out.clips, paths)
        filename = f"{cl_out.name.replace(' ', '_')}.fcpxml"

    elif fmt == "otio":
        content = _otio(cl_out.name, cl_out.clips, paths)
        filename = f"{cl_out.name.replace(' ', '_')}.otio"

    elif fmt == "json":
        content = json.dumps(
            {"name": cl_out.name, "clips": [c.model_dump() for c in cl_out.clips]},
            indent=2, default=str,
        )
        filename = f"{cl_out.name.replace(' ', '_')}.json"

    elif fmt == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["clip_id", "filename", "start_time", "end_time", "label"])
        for c in cl_out.clips:
            writer.writerow([c.id, c.filename, c.start_time, c.end_time, c.label or ""])
        content = buf.getvalue()
        filename = f"{cl_out.name.replace(' ', '_')}.csv"

    else:
        lines = ["TITLE: " + cl_out.name, "FCM: NON-DROP FRAME", ""]
        for i, c in enumerate(cl_out.clips, 1):
            def tc(secs: float) -> str:
                h = int(secs // 3600)
                m = int((secs % 3600) // 60)
                s = int(secs % 60)
                f = int((secs % 1) * 25)
                return f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"
            lines.append(f"{i:03d}  AX       V     C        {tc(c.start_time)} {tc(c.end_time)} {tc(c.start_time)} {tc(c.end_time)}")
            lines.append(f"* FROM CLIP NAME: {c.filename}")
            if paths.get(c.media_id):
                lines.append(f"* SOURCE FILE: {_translate(paths[c.media_id])}")
            if c.label:
                lines.append(f"* COMMENT: {c.label}")
            lines.append("")
        content = "\n".join(lines)
        filename = f"{cl_out.name.replace(' ', '_')}.edl"

    return ClipExportResult(format=fmt, content=content, filename=filename)


@router.post("/{id}/roughcut", response_model=ReelJobOut, status_code=202)
async def create_clip_list_rough_cut(
    id: str, body: RoughCutInput | None = None, db: AsyncSession = Depends(get_db)
):
    body = body or RoughCutInput()
    if body.preset not in ("original", "vertical"):
        raise HTTPException(status_code=400, detail="Preset must be original or vertical")

    cl = await _load_clip_list(id, db)
    cl_out = await _build_clip_list_out(cl, db)
    if not cl_out.clips:
        raise HTTPException(status_code=409, detail="Clip list is empty")

    from ..models import ReelJob
    reel = ReelJob(
        prompt=f"Rough cut — {cl_out.name}",
        media_id=None,
        project_id=cl.project_id,
        preset=body.preset,
        burn_captions=body.burn_captions,
        unreviewed=any(not c.approved for c in cl_out.clips),
        clips=[
            {
                "media_id": c.media_id,
                "filename": c.filename,
                "start_time": c.start_time,
                "end_time": c.end_time,
                "snippet": c.label,
            }
            for c in cl_out.clips
        ],
        status="pending",
    )
    db.add(reel)
    await touch_project(db, cl.project_id)
    await db.commit()
    await db.refresh(reel)

    from ..worker_client import enqueue_reel
    await enqueue_reel(reel.id)

    from .reels import _to_out
    return _to_out(reel)


@router.post("/{id}/render", response_model=list[RenderJobOut], status_code=202)
async def render_clip_list(id: str, body: RenderPresetInput, db: AsyncSession = Depends(get_db)):
    from .renders import create_renders_for_clip_list
    return await create_renders_for_clip_list(id, body.preset, body.burn_captions, db)
