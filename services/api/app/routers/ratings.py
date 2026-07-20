"""Provider-agnostic audience ratings (TV measurement).

CSV import today; the `provider` + `import_id` columns are the seam for a
future automated measurement-API ingest (no schema changes needed — a worker
task would just create an import batch and insert records the same way).
`is_own` is never stored: it is computed at read time from the OWN_STATIONS
env so a callsign change never requires a data migration.
"""
import csv
import io
import re
from collections import defaultdict
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import get_db
from ..models import MediaAsset, RatingRecord, RatingsImportBatch
from ..schemas import (
    RatingRecordOut,
    RatingsImportOut,
    RatingsKpisOut,
    RatingsListOut,
    RatingsOverviewOut,
    RatingsStationShareOut,
    RatingsTopProgramOut,
    RatingsTrendPointOut,
    RatingUpdateIn,
)

router = APIRouter(prefix="/ratings", tags=["ratings"])

MAX_IMPORT_BYTES = 20 * 1024 * 1024
MAX_ERRORS_REPORTED = 5

# Lenient header mapping — mirror of the mock server's RATINGS_HEADER_ALIASES.
HEADER_ALIASES = {
    "date": "air_date", "air_date": "air_date", "airdate": "air_date",
    "station": "station", "channel": "station", "call_letters": "station",
    "program": "program_title", "program_title": "program_title",
    "program_name": "program_title", "title": "program_title",
    "start": "start_time", "start_time": "start_time", "time": "start_time",
    "end": "end_time", "end_time": "end_time",
    "rating": "rating", "hh_rtg": "rating", "hh_rating": "rating", "rtg": "rating",
    "share": "share", "hh_share": "share", "shr": "share",
    "viewers": "viewers", "impressions": "viewers", "impressions_000": "viewers",
    "avg_audience": "viewers", "aa_000": "viewers",
    "market": "market", "dma": "market",
}


def own_station_set() -> set[str]:
    return {s.strip().upper() for s in settings.own_stations.split(",") if s.strip()}


def _norm_header(h: str) -> str:
    return re.sub(r"^_+|_+$", "", re.sub(r"[^a-z0-9+-]+", "_", h.strip().lower()))


def _parse_date(v: str) -> date | None:
    v = v.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        try:
            return date.fromisoformat(v)
        except ValueError:
            return None
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", v)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
        except ValueError:
            return None
    return None


def _num(v: str | None) -> float | None:
    if v is None or not str(v).strip():
        return None
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return None


def _round1(v: float | None) -> float | None:
    return None if v is None else round(v, 1)


def _rating_out(r: RatingRecord, own: set[str], asset_filename: str | None) -> RatingRecordOut:
    return RatingRecordOut(
        id=r.id,
        provider=r.provider,
        market=r.market,
        station=r.station,
        program_title=r.program_title,
        air_date=r.air_date.isoformat(),
        start_time=r.start_time,
        end_time=r.end_time,
        rating=r.rating,
        share=r.share,
        viewers=r.viewers,
        demo=r.demo,
        is_own=r.station.upper() in own,
        asset_id=r.asset_id,
        asset_filename=asset_filename,
        import_id=r.import_id,
    )


@router.get("", response_model=RatingsListOut)
async def list_ratings(
    from_: date | None = Query(None, alias="from"),
    to: date | None = None,
    station: str | None = None,
    provider: str | None = None,
    q: str | None = None,
    asset_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    limit = max(1, min(500, limit))
    offset = max(0, offset)

    filters = []
    if from_:
        filters.append(RatingRecord.air_date >= from_)
    if to:
        filters.append(RatingRecord.air_date <= to)
    if station:
        filters.append(func.upper(RatingRecord.station) == station.upper())
    if provider:
        filters.append(RatingRecord.provider == provider)
    if q:
        filters.append(RatingRecord.program_title.ilike(f"%{q}%"))
    if asset_id:
        filters.append(RatingRecord.asset_id == asset_id)

    total = (
        await db.execute(select(func.count()).select_from(RatingRecord).where(*filters))
    ).scalar_one()

    rows = (
        await db.execute(
            select(RatingRecord, MediaAsset.filename)
            .outerjoin(MediaAsset, MediaAsset.id == RatingRecord.asset_id)
            .where(*filters)
            .order_by(
                RatingRecord.air_date.desc(),
                RatingRecord.start_time.desc().nulls_last(),
                RatingRecord.station,
            )
            .offset(offset)
            .limit(limit)
        )
    ).all()

    own = own_station_set()
    return RatingsListOut(
        items=[_rating_out(r, own, fn) for r, fn in rows],
        total=int(total),
    )


# NOTE: FastAPI maps the reserved-word query param `from` via alias.
@router.get("/overview", response_model=RatingsOverviewOut)
async def ratings_overview(
    from_: date | None = Query(None, alias="from"),
    to: date | None = None,
    db: AsyncSession = Depends(get_db),
):
    to = to or date.today()
    from_ = from_ or date.fromordinal(to.toordinal() - 29)
    own = own_station_set()

    rows = (
        await db.execute(
            select(
                RatingRecord.station,
                RatingRecord.program_title,
                RatingRecord.air_date,
                RatingRecord.rating,
                RatingRecord.share,
                RatingRecord.viewers,
            ).where(RatingRecord.air_date >= from_, RatingRecord.air_date <= to)
        )
    ).all()

    own_rows = [r for r in rows if r.station.upper() in own]

    def avg(vals: list[float | None]) -> float | None:
        present = [v for v in vals if v is not None]
        return _round1(sum(present) / len(present)) if present else None

    by_date: dict[date, list] = defaultdict(list)
    for r in own_rows:
        by_date[r.air_date].append(r)
    trend = [
        RatingsTrendPointOut(
            date=d.isoformat(),
            avg_rating=avg([r.rating for r in day_rows]),
            avg_share=avg([r.share for r in day_rows]),
            total_viewers=(
                sum(r.viewers or 0 for r in day_rows)
                if any(r.viewers is not None for r in day_rows)
                else None
            ),
        )
        for d, day_rows in sorted(by_date.items())
    ]

    by_station: dict[str, list] = defaultdict(list)
    for r in rows:
        by_station[r.station].append(r)
    station_shares = sorted(
        (
            RatingsStationShareOut(
                station=st,
                is_own=st.upper() in own,
                avg_rating=avg([r.rating for r in st_rows]),
                avg_share=avg([r.share for r in st_rows]),
                record_count=len(st_rows),
            )
            for st, st_rows in by_station.items()
        ),
        key=lambda s: s.avg_share if s.avg_share is not None else -1,
        reverse=True,
    )

    by_program: dict[tuple[str, str], list] = defaultdict(list)
    for r in own_rows:
        by_program[(r.program_title, r.station)].append(r)
    top_programs = sorted(
        (
            RatingsTopProgramOut(
                program_title=title,
                station=st,
                airings=len(p_rows),
                avg_rating=avg([r.rating for r in p_rows]),
                avg_share=avg([r.share for r in p_rows]),
                best_rating=max(
                    (r.rating for r in p_rows if r.rating is not None), default=None
                ),
            )
            for (title, st), p_rows in by_program.items()
        ),
        key=lambda p: p.avg_rating if p.avg_rating is not None else -1,
        reverse=True,
    )[:10]

    viewers_vals = [r.viewers for r in own_rows if r.viewers is not None]
    return RatingsOverviewOut(
        own_stations=sorted(own),
        kpis=RatingsKpisOut(
            record_count=len(own_rows),
            program_count=len({r.program_title for r in own_rows}),
            avg_rating=avg([r.rating for r in own_rows]),
            avg_share=avg([r.share for r in own_rows]),
            peak_viewers=max(viewers_vals) if viewers_vals else None,
        ),
        trend=trend,
        station_shares=station_shares,
        top_programs=top_programs,
    )


@router.post("/import", response_model=RatingsImportOut, status_code=201)
async def import_ratings(
    file: UploadFile = File(...),
    provider: str = Form("manual"),
    market: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
):
    raw = await file.read(MAX_IMPORT_BYTES + 1)
    await file.close()
    if len(raw) > MAX_IMPORT_BYTES:
        raise HTTPException(status_code=413, detail="CSV exceeds the 20 MB import limit")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")

    reader = csv.reader(io.StringIO(text))
    lines = [row for row in reader if any(c.strip() for c in row)]
    if len(lines) < 2:
        raise HTTPException(status_code=400, detail="CSV has no data rows")

    headers = [_norm_header(h) for h in lines[0]]
    fields: list[tuple[str, str]] = []
    for h in headers:
        if h.startswith("demo_"):
            fields.append(("demo", h[5:]))
        elif h in HEADER_ALIASES:
            fields.append(("field", HEADER_ALIASES[h]))
        else:
            fields.append(("skip", h))
    mapped = {key for kind, key in fields if kind == "field"}
    if not {"air_date", "station", "program_title"} <= mapped:
        raise HTTPException(
            status_code=400,
            detail="CSV must include date, station, and program columns",
        )

    batch = RatingsImportBatch(
        filename=file.filename or "ratings.csv", provider=provider
    )
    db.add(batch)
    await db.flush()

    errors: list[str] = []
    inserted = 0
    for i, cells in enumerate(lines[1:], start=2):
        row: dict = {}
        demo: dict[str, float] | None = None
        for (kind, key), cell in zip(fields, cells):
            v = cell.strip()
            if not v:
                continue
            if kind == "demo":
                n = _num(v)
                if n is not None:
                    demo = demo or {}
                    demo[key] = n
            elif kind == "field":
                row[key] = v
        air = _parse_date(row.get("air_date", ""))
        if not air or not row.get("station") or not row.get("program_title"):
            if len(errors) < MAX_ERRORS_REPORTED:
                errors.append(f"Row {i}: missing/invalid date, station, or program")
            continue
        viewers = _num(row.get("viewers"))
        db.add(
            RatingRecord(
                import_id=batch.id,
                provider=provider,
                market=row.get("market") or market,
                station=row["station"].upper(),
                program_title=row["program_title"],
                air_date=air,
                start_time=row.get("start_time"),
                end_time=row.get("end_time"),
                rating=_num(row.get("rating")),
                share=_num(row.get("share")),
                viewers=int(round(viewers)) if viewers is not None else None,
                demo=demo,
            )
        )
        inserted += 1

    error_count = len(lines) - 1 - inserted
    if inserted == 0:
        await db.rollback()
        raise HTTPException(
            status_code=400, detail=f"No valid rows ({error_count} skipped)"
        )

    batch.row_count = inserted
    batch.error_count = error_count
    await db.commit()
    return RatingsImportOut(
        id=batch.id,
        filename=batch.filename,
        provider=batch.provider,
        row_count=inserted,
        error_count=error_count,
        errors=errors or None,
        created_at=batch.created_at.isoformat(),
    )


@router.get("/imports", response_model=list[RatingsImportOut])
async def list_imports(db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(
            select(RatingsImportBatch).order_by(RatingsImportBatch.created_at.desc())
        )
    ).scalars().all()
    return [
        RatingsImportOut(
            id=b.id,
            filename=b.filename,
            provider=b.provider,
            row_count=b.row_count,
            error_count=b.error_count,
            errors=None,
            created_at=b.created_at.isoformat(),
        )
        for b in rows
    ]


@router.delete("/imports/{import_id}", status_code=204)
async def delete_import(import_id: str, db: AsyncSession = Depends(get_db)):
    batch = (
        await db.execute(
            select(RatingsImportBatch).where(RatingsImportBatch.id == import_id)
        )
    ).scalar_one_or_none()
    if not batch:
        raise HTTPException(status_code=404, detail="Import not found")
    await db.execute(delete(RatingRecord).where(RatingRecord.import_id == import_id))
    await db.delete(batch)
    await db.commit()


@router.patch("/{rating_id}", response_model=RatingRecordOut)
async def update_rating(
    rating_id: str, body: RatingUpdateIn, db: AsyncSession = Depends(get_db)
):
    rec = (
        await db.execute(select(RatingRecord).where(RatingRecord.id == rating_id))
    ).scalar_one_or_none()
    if not rec:
        raise HTTPException(status_code=404, detail="Rating record not found")

    asset_filename: str | None = None
    if "asset_id" in body.model_fields_set:
        if body.asset_id is not None:
            asset = (
                await db.execute(
                    select(MediaAsset).where(MediaAsset.id == body.asset_id)
                )
            ).scalar_one_or_none()
            if not asset:
                raise HTTPException(status_code=404, detail="Asset not found")
            rec.asset_id = body.asset_id
            asset_filename = asset.filename
        else:
            rec.asset_id = None
        await db.commit()
        await db.refresh(rec)
    elif rec.asset_id:
        asset_filename = (
            await db.execute(
                select(MediaAsset.filename).where(MediaAsset.id == rec.asset_id)
            )
        ).scalar_one_or_none()

    return _rating_out(rec, own_station_set(), asset_filename)
