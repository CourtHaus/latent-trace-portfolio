"""Regression: the public read API must serve ONLY published dataset versions.

SEC-2026-05-31-A. An operator can pull a dataset from public view with the
admin "unpublish" control, which flips ``etl.dataset_version.ingestion_status``
to ``'archived'`` WITHOUT deleting the dataset's cases. Before the fix, every
public read surface (list, map, detail, photo, filter-options, year-histogram,
facet-counts, sources-summary) ignored ``ingestion_status`` and kept serving the
archived rows — the takedown control was a silent no-op for anonymous users.

Each test seeds a corpus (born ``'published'`` via the seed helper), asserts the
case is visible on a surface, flips the dataset version to ``'archived'``, and
asserts it has disappeared. The same gate also hides ``'draft'`` / ``'validated'``
/ ``'failed'`` versions; ``'archived'`` is the representative non-published state.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from tests.integration._seed import (
    CaseSpec,
    ExtractionSpec,
    PhotoSpec,
    SeededCorpus,
    SeedFn,
    VictimSpec,
)

if not os.getenv("DATABASE_URL"):
    pytest.skip(
        "DATABASE_URL not set; skipping integration test", allow_module_level=True
    )

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True, scope="module")
def _disable_rate_limiter() -> Iterator[None]:
    """Insulate these visibility tests from the shared in-memory rate limiter.

    slowapi's limiter is a module-level singleton with one bucket per IP that
    persists across every TestClient in a single pytest process. In a full
    single-process run the public /cold-cases routes (60/min) can already exceed
    that bucket independent of this module — a pre-existing, timing-dependent
    flake. Disable the limiter for this module so these data-visibility
    assertions are deterministic, then restore the prior state so the dedicated
    rate-limit tests elsewhere are unaffected.
    """
    from casesignal.api.middleware.rate_limit import limiter

    prior = limiter.enabled
    limiter.enabled = False
    try:
        yield
    finally:
        limiter.enabled = prior


# Collision-free markers so global (un-filtered) endpoints can assert on this
# corpus alone, undisturbed by whatever real data sits in the dev DB.
_CODE = "SECVIS_TEST"
_STATE = "ZQ"
_CITY = "Sectestville"
# weapon / location_type are controlled vocabularies (CHECK constraint); use
# real values. They're not collision markers — assertions scope by source_system
# / state / city, which are corpus-unique.
_WEAPON = "firearm"
_LOCATION = "residence"
_RACE = "sectest_race"
_YEAR = 1903
_SCID = "SECVIS-1"
_PHOTO = "photo.jpg"

_CASES = [
    CaseSpec(
        source_case_id=_SCID,
        case_name="Sec Vis Test Case",
        state=_STATE,
        city=_CITY,
        incident_date=f"{_YEAR}-06-15",
        latitude=44.26,
        longitude=-72.58,
        geocode_precision="street",
        victims=[VictimSpec(gender="M", race=_RACE)],
        photos=[PhotoSpec(filename=_PHOTO, storage_path=f"{_CODE}/{_SCID}/{_PHOTO}")],
        extractions=[
            ExtractionSpec(prompt_tier=1, weapon=_WEAPON, location_type=_LOCATION)
        ],
    )
]


def _published_corpus(seed: SeedFn) -> SeededCorpus:
    return seed(_CODE, _CASES, source_state=_STATE)


def _archive(corpus: SeededCorpus) -> None:
    """Flip the corpus's dataset version to 'archived' (what admin unpublish does)."""
    with corpus._session_factory() as s:
        s.execute(
            text(
                "UPDATE etl.dataset_version SET ingestion_status = 'archived', "
                "published_at = NULL WHERE dataset_version_id = :dv"
            ),
            {"dv": corpus.dataset_version_id},
        )
        s.commit()


def _json(resp: Any) -> dict[str, Any]:
    assert resp.status_code == 200, resp.text
    return resp.json()  # type: ignore[no-any-return]


def test_list_excludes_archived(public_client: TestClient, seed: SeedFn) -> None:
    corpus = _published_corpus(seed)
    cid = corpus.case_ids[_SCID]

    before = _json(public_client.get(f"/api/v1/cold-cases?source_system={_CODE}"))
    assert before["meta"]["total"] == 1
    assert [r["case_id"] for r in before["data"]] == [cid]

    _archive(corpus)

    after = _json(public_client.get(f"/api/v1/cold-cases?source_system={_CODE}"))
    assert after["meta"]["total"] == 0
    assert after["data"] == []
    # total_unfiltered is the public corpus size — it must drop the archived row.
    assert before["meta"]["total_unfiltered"] - after["meta"]["total_unfiltered"] == 1


def test_map_excludes_archived(public_client: TestClient, seed: SeedFn) -> None:
    corpus = _published_corpus(seed)
    cid = corpus.case_ids[_SCID]
    url = f"/api/v1/cold-cases/map?bbox=-180,-90,180,90&source_system={_CODE}"

    before = _json(public_client.get(url))
    assert before["mode"] == "points"
    assert cid in [r["case_id"] for r in before["data"]]

    _archive(corpus)

    after = _json(public_client.get(url))
    assert after["data"] == []
    assert before["meta"]["total_unfiltered"] - after["meta"]["total_unfiltered"] == 1


def test_detail_excludes_archived(public_client: TestClient, seed: SeedFn) -> None:
    corpus = _published_corpus(seed)
    cid = corpus.case_ids[_SCID]

    assert public_client.get(f"/api/v1/cold-cases/{cid}").status_code == 200

    _archive(corpus)

    assert public_client.get(f"/api/v1/cold-cases/{cid}").status_code == 404


def test_filter_options_excludes_archived(
    public_client: TestClient, seed: SeedFn
) -> None:
    corpus = _published_corpus(seed)

    before = _json(public_client.get("/api/v1/cold-cases/filter-options"))
    assert _STATE in before["states"]
    assert _CITY in before["cities"]
    assert _CODE in [s["code"] for s in before["source_systems"]]

    _archive(corpus)

    after = _json(public_client.get("/api/v1/cold-cases/filter-options"))
    # Scope assertions to corpus-unique values. weapon/location_type use shared
    # controlled-vocab values ('firearm'/'residence'), and race now folds to
    # shared canonical buckets ('sectest_race' -> 'Other'), so none of those can
    # be asserted to vanish from a single archived corpus — state/city/source are
    # the corpus-unique sentinels that prove the gate.
    assert _STATE not in after["states"]
    assert _CITY not in after["cities"]
    assert _CODE not in [s["code"] for s in after["source_systems"]]


def _year_count(body: dict[str, Any], year: int) -> int:
    for b in body["buckets"]:
        if b["year"] == year:
            return int(b["count"])
    return 0


def test_year_histogram_excludes_archived(
    public_client: TestClient, seed: SeedFn
) -> None:
    corpus = _published_corpus(seed)

    before = _json(public_client.get("/api/v1/cold-cases/year-histogram"))
    _archive(corpus)
    after = _json(public_client.get("/api/v1/cold-cases/year-histogram"))

    assert _year_count(before, _YEAR) - _year_count(after, _YEAR) == 1


def test_facet_counts_exclude_archived(
    public_client: TestClient, seed: SeedFn
) -> None:
    corpus = _published_corpus(seed)

    before = _json(public_client.get("/api/v1/cold-cases/facet-counts"))
    assert _CODE in [f["value"] for f in before["source_system"]]
    assert _STATE in [f["value"] for f in before["state"]]

    _archive(corpus)

    after = _json(public_client.get("/api/v1/cold-cases/facet-counts"))
    assert _CODE not in [f["value"] for f in after["source_system"]]
    assert _STATE not in [f["value"] for f in after["state"]]


def test_sources_summary_excludes_archived(
    public_client: TestClient, seed: SeedFn
) -> None:
    corpus = _published_corpus(seed)

    before = _json(public_client.get("/api/v1/cold-cases/sources-summary"))
    assert _CODE in [s["code"] for s in before["data"]]

    _archive(corpus)

    after = _json(public_client.get("/api/v1/cold-cases/sources-summary"))
    assert _CODE not in [s["code"] for s in after["data"]]


@pytest.fixture
def _photo_on_disk() -> Iterator[None]:
    """Write a real file at the route's resolved photo path so the photo
    endpoint reaches its DB-gated 200 path; the visibility gate is the DB
    lookup, so an archived case must 404 even though the file exists."""
    from casesignal.api.routes.cold_cases import _PHOTOS_ROOT

    target = _PHOTOS_ROOT / _CODE / _SCID / _PHOTO
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"\xff\xd8\xff\xe0sectest")
    try:
        yield
    finally:
        try:
            target.unlink()
            target.parent.rmdir()
            target.parent.parent.rmdir()
        except OSError:
            pass


def test_photo_excludes_archived(
    public_client: TestClient, seed: SeedFn, _photo_on_disk: None
) -> None:
    corpus = _published_corpus(seed)
    cid = corpus.case_ids[_SCID]
    url = f"/api/v1/cold-cases/{cid}/photos/{_PHOTO}"

    assert public_client.get(url).status_code == 200

    _archive(corpus)

    assert public_client.get(url).status_code == 404
