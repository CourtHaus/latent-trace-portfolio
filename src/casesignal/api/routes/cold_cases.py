from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

import casesignal.etl
from casesignal.api.dependencies.db import get_db_session
from casesignal.api.middleware.rate_limit import limiter
from casesignal.api.schemas.cold_cases import (
    CaseDetailResponse,
    ColdCaseListMeta,
    ColdCaseListResponse,
    ColdCaseMapClusterItem,
    ColdCaseMapItem,
    ColdCaseMapMeta,
    ColdCaseMapResponse,
    CoverageHistogramResponse,
    FacetCountsResponse,
    FilterOptionsResponse,
    SortOrder,
    SourcesSummaryResponse,
    YearHistogramResponse,
)
from casesignal.api.services.cold_cases import (
    CLUSTER_ZOOM_THRESHOLD,
    DEFAULT_MAP_LIMIT,
    MAX_MAP_LIMIT,
    aggregate_cold_cases_for_map,
    get_cold_case_by_id,
    get_coverage_histogram,
    get_facet_counts,
    get_filter_options,
    get_sources_summary,
    get_year_histogram,
    list_cold_cases,
    parse_bbox,
    query_cold_cases_for_map,
)
from casesignal.correlation.schemas import CorrelationCandidatesResponse
from casesignal.correlation.service import get_correlation_candidates
from casesignal.etl.services.source_catalog import SourceCatalog
from casesignal.storage.photo_storage import fetch_photo_from_supabase

_PHOTOS_ROOT = Path(os.getenv("CASESIGNAL_PHOTOS_ROOT", "data/photos")).resolve()


def _build_source_code_to_photo_dir() -> dict[str, str]:
    """Map each source_code to its on-disk photo directory.

    Every cold-case adapter's raw_load writes photos to
    ``data/photos/<adapter_name>/<source_case_id>/``. The photo endpoint
    needs source_code -> adapter_name to locate them. This is derived from
    the source catalog so a newly-added adapter needs no change here — the
    previous hand-maintained map carried only the Phase-1 BCounty entry and
    silently 404'd every photo-bearing state added afterwards.
    """
    sources_dir = Path(casesignal.etl.__file__).resolve().parent / "sources"
    catalog = SourceCatalog.from_yaml(sources_dir)
    return {sd.source_code: sd.adapter_name for sd in catalog.list_sources()}


# Built once at import. A newly-added source YAML is picked up on restart.
_SOURCE_CODE_TO_PHOTO_DIR = _build_source_code_to_photo_dir()


router = APIRouter(prefix="/cold-cases", tags=["cold-cases"])

_AGGREGATE_CACHE_CONTROL = "max-age=3600, stale-while-revalidate=86400"


@router.get("", response_model=ColdCaseListResponse)
@limiter.limit("60/minute")
def get_cold_cases_list(
    request: Request,
    response: Response,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    sort: SortOrder = Query(default=SortOrder.incident_date_desc),
    case_type: str | None = Query(
        default=None,
        max_length=256,
        description="Comma-separated for multi-value (e.g., 'homicide,missing_person').",
    ),
    year_min: int | None = Query(default=None, ge=1900, le=2100),
    year_max: int | None = Query(default=None, ge=1900, le=2100),
    city: str | None = Query(default=None, max_length=128),
    state: str | None = Query(default=None, max_length=2),
    gender: str | None = Query(
        default=None,
        max_length=128,
        description="Comma-separated for multi-value.",
    ),
    race: str | None = Query(
        default=None,
        max_length=128,
        description="Comma-separated for multi-value.",
    ),
    weapon: str | None = Query(
        default=None,
        max_length=128,
        description="Comma-separated for multi-value (e.g., 'firearm,knife').",
    ),
    location_type: str | None = Query(
        default=None,
        max_length=128,
        description="Comma-separated for multi-value (e.g., 'residence,public_outdoor').",
    ),
    source_system: str | None = Query(
        default=None,
        max_length=256,
        description="Comma-separated source-system codes (e.g., 'VSPCCD_VA,MPDC_DC_PD').",
    ),
    precision: str | None = Query(
        default=None,
        max_length=128,
        description="Comma-separated geocode_precision tiers (street, landmark, zip, county, failed).",
    ),
    q: str | None = Query(default=None, min_length=2, max_length=100),
    session: Session = Depends(get_db_session),
) -> ColdCaseListResponse:
    rows, total, total_unfiltered = list_cold_cases(
        session,
        limit=limit,
        offset=offset,
        sort=sort,
        case_type=_split_csv(case_type),
        year_min=year_min,
        year_max=year_max,
        city=city,
        state=state,
        gender=_split_csv(gender),
        race=_split_csv(race),
        weapon=_split_csv(weapon),
        location_type=_split_csv(location_type),
        source_system=_split_csv(source_system),
        precision=_split_csv(precision),
        q=q,
    )
    response.headers["Cache-Control"] = _AGGREGATE_CACHE_CONTROL
    return ColdCaseListResponse(
        data=rows,
        meta=ColdCaseListMeta(
            total=total,
            offset=offset,
            limit=limit,
            total_unfiltered=total_unfiltered,
        ),
    )


def _split_csv(value: str | None) -> list[str] | None:
    """Split a comma-separated query param into a list.

    Returns None for None input or an empty/whitespace-only string so the
    service's ``IS NULL`` short-circuit applies and no filter is added.
    """
    if value is None:
        return None
    parts = [p.strip() for p in value.split(",") if p.strip()]
    return parts or None


@router.get("/map", response_model=ColdCaseMapResponse)
@limiter.limit("60/minute")
def get_cold_cases_map(
    request: Request,
    response: Response,
    bbox: str | None = Query(
        default=None,
        description="west,south,east,north (decimal degrees, WGS84). Absent = no geographic filter.",
    ),
    case_type: str | None = Query(
        default=None,
        max_length=256,
        description="Comma-separated for multi-value (e.g., 'homicide,missing_person').",
    ),
    year_min: int | None = Query(default=None, ge=1900, le=2100),
    year_max: int | None = Query(default=None, ge=1900, le=2100),
    state: str | None = Query(default=None, max_length=2),
    city: str | None = Query(default=None, max_length=128),
    gender: str | None = Query(
        default=None,
        max_length=128,
        description="Comma-separated for multi-value.",
    ),
    race: str | None = Query(
        default=None,
        max_length=128,
        description="Comma-separated for multi-value.",
    ),
    age_min: int | None = Query(default=None, ge=0, le=150),
    age_max: int | None = Query(default=None, ge=0, le=150),
    weapon: str | None = Query(
        default=None,
        max_length=128,
        description="Comma-separated for multi-value.",
    ),
    location_type: str | None = Query(
        default=None,
        max_length=128,
        description="Comma-separated for multi-value.",
    ),
    source_system: str | None = Query(
        default=None,
        max_length=256,
        description="Comma-separated source-system codes (e.g., 'VSPCCD_VA,MPDC_DC_PD').",
    ),
    precision: str | None = Query(
        default=None,
        max_length=128,
        description="Comma-separated geocode_precision tiers (street, landmark, zip, county, failed).",
    ),
    limit: int = Query(default=DEFAULT_MAP_LIMIT, ge=1, le=MAX_MAP_LIMIT),
    zoom: int | None = Query(
        default=None,
        ge=0,
        le=22,
        description=(
            "Leaflet zoom level. Below the cluster threshold the map returns "
            "server-aggregated clusters; at or above it, individual points. "
            "Absent = individual points (historical behavior)."
        ),
    ),
    session: Session = Depends(get_db_session),
) -> ColdCaseMapResponse:
    parsed_bbox: tuple[float, float, float, float] | None = None
    if bbox is not None:
        try:
            parsed_bbox = parse_bbox(bbox)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc

    filter_kwargs: dict[str, object] = {
        "case_type": _split_csv(case_type),
        "year_min": year_min,
        "year_max": year_max,
        "state": state,
        "city": city,
        "gender": _split_csv(gender),
        "race": _split_csv(race),
        "age_min": age_min,
        "age_max": age_max,
        "weapon": _split_csv(weapon),
        "location_type": _split_csv(location_type),
        "source_system": _split_csv(source_system),
        "precision": _split_csv(precision),
    }

    # Clusters only when zoom is explicitly below the threshold. Absent zoom
    # falls through to individual points — historical behavior, and keeps a
    # bare API call backward-compatible. The frontend always sends zoom.
    if zoom is not None and zoom < CLUSTER_ZOOM_THRESHOLD:
        clusters, total_unfiltered = aggregate_cold_cases_for_map(
            session,
            parsed_bbox,
            zoom=zoom,
            **filter_kwargs,  # type: ignore[arg-type]
        )
        response.headers["Cache-Control"] = _AGGREGATE_CACHE_CONTROL
        return ColdCaseMapResponse(
            mode="clusters",
            clusters=[ColdCaseMapClusterItem(**c) for c in clusters],
            meta=ColdCaseMapMeta(
                bbox=parsed_bbox,
                returned=len(clusters),
                truncated=False,
                total_unfiltered=total_unfiltered,
            ),
        )

    rows, truncated, total_unfiltered = query_cold_cases_for_map(
        session,
        parsed_bbox,
        limit=limit,
        **filter_kwargs,  # type: ignore[arg-type]
    )

    response.headers["Cache-Control"] = _AGGREGATE_CACHE_CONTROL
    return ColdCaseMapResponse(
        mode="points",
        data=[ColdCaseMapItem(**r) for r in rows],
        meta=ColdCaseMapMeta(
            bbox=parsed_bbox,
            returned=len(rows),
            truncated=truncated,
            total_unfiltered=total_unfiltered,
        ),
    )


@router.get("/filter-options", response_model=FilterOptionsResponse)
@limiter.limit("60/minute")
def get_cold_cases_filter_options(
    request: Request,
    response: Response,
    session: Session = Depends(get_db_session),
) -> FilterOptionsResponse:
    """Distinct values across the dataset for UI filter option lists.

    Cache lifecycle: 1 hour when MO extractions are present in the response.
    5 minutes when both weapons and location_types are empty (deploy
    bootstrap state — extractions haven't run yet, dropdowns shouldn't stay
    empty for an hour). Self-healing: as soon as the first extraction is
    written, subsequent responses carry the long cache.
    """
    options = get_filter_options(session)
    if not options.weapons and not options.location_types:
        response.headers["Cache-Control"] = "max-age=300, stale-while-revalidate=600"
    else:
        response.headers["Cache-Control"] = _AGGREGATE_CACHE_CONTROL
    return options


@router.get("/sources-summary", response_model=SourcesSummaryResponse)
@limiter.limit("60/minute")
def get_cold_cases_sources_summary(
    request: Request,
    response: Response,
    session: Session = Depends(get_db_session),
) -> SourcesSummaryResponse:
    """Per-source aggregates: case count, geocoded count, year range, state.

    Drives the methodology page coverage table + map. Cached aggressively
    since the underlying data only changes on ingestion.
    """
    summary = get_sources_summary(session)
    response.headers["Cache-Control"] = _AGGREGATE_CACHE_CONTROL
    return summary


@router.get("/facet-counts", response_model=FacetCountsResponse)
@limiter.limit("60/minute")
def get_cold_cases_facet_counts(
    request: Request,
    response: Response,
    case_type: str | None = Query(default=None, max_length=256),
    year_min: int | None = Query(default=None, ge=1900, le=2100),
    year_max: int | None = Query(default=None, ge=1900, le=2100),
    city: str | None = Query(default=None, max_length=128),
    state: str | None = Query(default=None, max_length=2),
    gender: str | None = Query(default=None, max_length=128),
    race: str | None = Query(default=None, max_length=128),
    weapon: str | None = Query(default=None, max_length=128),
    location_type: str | None = Query(default=None, max_length=128),
    source_system: str | None = Query(default=None, max_length=256),
    precision: str | None = Query(default=None, max_length=128),
    q: str | None = Query(default=None, min_length=2, max_length=100),
    session: Session = Depends(get_db_session),
) -> FacetCountsResponse:
    """Faceted per-facet case counts plus geocoded + total scalars.

    Accepts the same filter params as the list endpoint. Each facet's counts
    exclude that facet's own selection (so sibling checkboxes keep their counts)
    while reflecting every other active filter; total/geocoded apply all
    filters. With no filters it's the corpus-wide totals the landing bars use.
    Cached per filter-combination — underlying data only changes on ingestion.
    """
    counts = get_facet_counts(
        session,
        case_type=_split_csv(case_type),
        year_min=year_min,
        year_max=year_max,
        city=city,
        state=state,
        gender=_split_csv(gender),
        race=_split_csv(race),
        weapon=_split_csv(weapon),
        location_type=_split_csv(location_type),
        source_system=_split_csv(source_system),
        precision=_split_csv(precision),
        q=q,
    )
    response.headers["Cache-Control"] = _AGGREGATE_CACHE_CONTROL
    return counts


@router.get("/year-histogram", response_model=YearHistogramResponse)
@limiter.limit("60/minute")
def get_cold_cases_year_histogram(
    request: Request,
    response: Response,
    session: Session = Depends(get_db_session),
) -> YearHistogramResponse:
    """Per-year incident counts (+ undated remainder) for the decade histogram.
    Cached aggressively — only changes on ingestion.
    """
    histogram = get_year_histogram(session)
    response.headers["Cache-Control"] = _AGGREGATE_CACHE_CONTROL
    return histogram


@router.get("/coverage-histogram", response_model=CoverageHistogramResponse)
@limiter.limit("60/minute")
def get_cold_cases_coverage_histogram(
    request: Request,
    response: Response,
    session: Session = Depends(get_db_session),
) -> CoverageHistogramResponse:
    """Per-(state, decade) published-case counts for the coverage heatmap.
    Cached aggressively — only changes on ingestion."""
    result = get_coverage_histogram(session)
    response.headers["Cache-Control"] = _AGGREGATE_CACHE_CONTROL
    return result


@router.get("/{case_id}/correlation-candidates", response_model=CorrelationCandidatesResponse)
@limiter.limit("60/minute")
def get_cold_case_correlation_candidates(
    request: Request,
    case_id: int,
    response: Response,
    session: Session = Depends(get_db_session),
) -> CorrelationCandidatesResponse:
    """Full scored candidate pool + top-N leads for one focal case (landing joint plot)."""
    result = get_correlation_candidates(session, case_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Case not found")
    response.headers["Cache-Control"] = _AGGREGATE_CACHE_CONTROL
    return result


@router.get("/{case_id}", response_model=CaseDetailResponse)
@limiter.limit("60/minute")
def get_cold_case_detail(
    request: Request,
    case_id: int,
    session: Session = Depends(get_db_session),
) -> CaseDetailResponse:
    case = get_cold_case_by_id(session, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return case


@router.get(
    "/{case_id}/photos/{filename}",
    responses={
        200: {"content": {"image/*": {}}},
        404: {"description": "Photo not found"},
    },
)
@limiter.limit("120/minute")
def get_cold_case_photo(
    request: Request,
    case_id: int,
    filename: str,
    session: Session = Depends(get_db_session),
) -> Response:
    """Serve a stored photo for a case.

    Path resolution: data/photos/<source_key>/<source_case_id>/<filename>.
    Defense-in-depth: filename was sanitized at scrape time, but we
    Path.resolve() the joined path here too and verify it stays inside
    the photo root.
    """
    row = (
        session.execute(
            text("""
            SELECT cp.content_type, cp.storage_path, ss.source_code, c.source_case_id
              FROM cold_case.case_photo cp
              JOIN cold_case.cases c ON c.case_id = cp.case_id
              JOIN etl.dataset_version dv ON dv.dataset_version_id = c.dataset_version_id
               AND dv.ingestion_status = 'published'
              JOIN etl.source_system ss ON ss.source_system_id = dv.source_system_id
             WHERE cp.case_id = :cid AND cp.filename = :fn
             LIMIT 1
            """),
            {"cid": case_id, "fn": filename},
        )
        .mappings()
        .one_or_none()
    )

    if row is None:
        raise HTTPException(status_code=404, detail="Photo not found")

    # Prefer the recorded storage_path (true on-disk location, set by the
    # backfill). Fall back to catalog-derived <adapter>/<source_case_id>/
    # resolution for rows not yet backfilled.
    if row["storage_path"]:
        candidate = (_PHOTOS_ROOT / row["storage_path"]).resolve()
    else:
        source_dir = _SOURCE_CODE_TO_PHOTO_DIR.get(row["source_code"])
        if source_dir is None:
            raise HTTPException(status_code=404, detail="Photo not found")
        candidate = (_PHOTOS_ROOT / source_dir / row["source_case_id"] / filename).resolve()

    if _PHOTOS_ROOT not in candidate.parents and candidate != _PHOTOS_ROOT:
        # Path escaped — refuse.
        raise HTTPException(status_code=404, detail="Photo not found")

    if candidate.exists() and candidate.is_file():
        return FileResponse(
            candidate,
            media_type=row["content_type"],
            headers={
                "Cache-Control": "public, max-age=31536000, immutable",
            },
        )

    stored_photo = fetch_photo_from_supabase(
        row["storage_path"] or f"{source_dir}/{row['source_case_id']}/{filename}",
        content_type=row["content_type"],
    )
    if stored_photo is None:
        raise HTTPException(status_code=404, detail="Photo not found")

    return Response(
        content=stored_photo.content,
        media_type=stored_photo.content_type,
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
        },
    )
