"""Capture a JSON source: the whole feed when it fits, a scoped sample when it does not.

Three sub-shapes share one rule. Socrata pages with ``$limit``/``$offset`` under a
stable ``$order`` and ends on a short page; an ArcGIS FeatureServer pages with
``resultOffset``/``resultRecordCount`` and ends when it stops setting
``exceededTransferLimit``; an embedded payload is one page that already holds
everything. All three are paged to exhaustion when they fit under ``max_records``,
because taking the whole dataset is what lets a later pass assert an exact record
count against the fixtures.

That invariant is the reason most of the care here goes into *not* claiming one.
``records_captured == records_total`` is the census marker downstream, and a
census that is not one is worse than no census at all: it becomes an exact-count
assertion every generated parser satisfies, so the check that was supposed to
catch a half-parsed feed silently blesses it. So a walk that stopped at the cap
reports no total, and a walk that stopped for any reason the feed did not
authorise — an error envelope where an array was due, a body that is not JSON, a
payload holding things that are not records, an offset that stopped advancing —
says ``truncated`` and reports no total either. Reaching the end and parsing
nothing is the same move once more: an *unknown* total rather than a total of
zero.

Two totals here are real without being a census. An embedded payload larger than
the cap knows its own size exactly, because the whole thing is in hand and only
part of it was kept. An ArcGIS layer will answer ``returnCountOnly`` with the
size of the corpus the walk only sampled. Both are recorded as ``records_total``
above ``records_captured``, which is precisely the shape that tells a later pass
to scope its record-level assertions to the sample. Neither is ever allowed to
come back equal to what was captured; a "total" no larger than the sample is a
census claim wearing a total's clothes.

An embedded payload's own envelope is read for the four things that would make a
single request short of the corpus: a next-page pointer, a stated total larger than
the rows in hand, a page count above one, and a page size the rows exactly filled.
Each is read from the document and from a closed set of named envelope blocks
(``links``, ``_links``, ``meta``, ``pagination`` ...), because JSON:API and HAL --
between them, the paginated-JSON conventions -- put both signals one level down, and a
top-level-only read censused page one of each. Closed set rather than document-wide
scan, so a nav menu's ``{"nav": {"next": "/about"}}`` is still not pagination. "There is no second request to make here" holds for a payload
inside an HTML page and not for the plain JSON endpoints this sub-shape also covers,
and a stated total of 307 beside 50 real rows is the most dangerous false census
there is — the rows are records, so locators match, coverage is real, and the
exact-count invariant asserts 50 against a 307-record source. Neither finding is
followed; both are said, as ``truncated`` and as a total above what was captured.

The three sub-shapes are not equally entitled to a census, either. Socrata and
ArcGIS *earn* theirs: the feed says where its rows are and says when they run
out. An embedded payload says neither, so its record list has to be found in an
arbitrary document, and ``data``, ``items``, ``results`` and ``value`` name a
filter dropdown or a nav menu about as often as they name a case list. A census
off a right guess is indistinguishable from one off a wrong guess, and the wrong
one becomes an exact-count invariant that a parser scraping the nav menu
satisfies. So an embedded capture claims a total only when the document named its
record list and named exactly one; otherwise the rows are captured and the total
is withheld.

One coupling worth knowing before editing ``_ROW_KEYS``: it does two jobs. It names
the lists the search will consider as candidates, and it decides which lists the
search will not walk into. Adding or removing a word changes the traversal as well as
the vocabulary, and the traversal is where a hidden candidate becomes a false census.

Fixture naming, path containment, and resume live in
:mod:`casesignal.drafter.shapes.fixtures`. What matters at this layer is that
nothing a server said ever becomes a filename: a Socrata dataset id goes into a
URL percent-encoded as a single path segment and nowhere else, and fixture names
are counter-derived.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

from bs4 import BeautifulSoup

from casesignal.drafter import session as session_mod
from casesignal.drafter.session import CaptureSession
from casesignal.drafter.shapes import fixtures
from casesignal.drafter.shapes.base import (
    RECORD_LIST_AMBIGUOUS,
    RECORD_LIST_BOUNDED,
    RECORD_LIST_GUESSED,
    RECORD_LIST_NAMED,
    RECORD_LIST_UNREADABLE,
    RECORD_LIST_WRAPPED,
    CapturedRecord,
    CaptureResult,
    HttpClient,
)
from casesignal.scout.models import Candidate, Channel

# Where a JSON payload keeps its rows, most specific first. Tried at every level of
# a nested document before falling back to "any list of objects", so a wrapper key
# a framework happened to add cannot outrank the feed's own record list.
_ROW_KEYS = ("data", "features", "results", "records", "items", "rows", "cases", "value")

# How deep to look for that list inside an embedded document. Framework payloads
# (``__NEXT_DATA__`` and friends) bury it a few levels down; unbounded recursion
# through an arbitrary server document is not something to do politely.
_MAX_PAYLOAD_DEPTH = 6

# And how wide. The search descends through arrays as well as objects, so a large
# structural array would otherwise put every one of its elements on the next level
# and every one of their values on the level after that.
#
# Exhausting either bound leaves part of the document unexamined, and an unexamined
# part may hold a competing candidate — so a search that hit a bound cannot be
# evidence of how many candidates the document holds, and says so by refusing to be
# authoritative. Getting that wrong is not a missed census, it is a false one: a
# width bound that silently dropped a rival candidate would leave exactly one
# survivor and stamp the nav menu as the corpus. Both numbers are chosen rather
# than measured; what is not a matter of taste is that running out voids authority.
_MAX_PAYLOAD_NODES = 512

# A named list whose elements really are records is not walked into: that is what
# keeps a genuinely large feed — one ``data`` array holding a few thousand cases —
# from spending the width budget on its own records and losing the census it had
# already earned. "Really are records" is the load-bearing half, and skipping on the
# row key alone is not it. A group-wrapped document (``{"results": [{"page": 1,
# "data": [...]}]}``) names a list whose single element is a *wrapper*, and blinding
# the search to what that wrapper holds turns an ambiguous document into a singly
# named one: an authoritative census of one wrapper object with the real cases a
# level below, uncounted. See _holds_a_record_list.
_ROW_KEY_SET = frozenset(_ROW_KEYS)

# How far inside one element of a named list to look for the record list it may be
# wrapping, and how many container nodes that search may visit before it gives up.
# Two levels covers ``{"page": {"cases": [...]}}``; four leaves room for the extra
# nesting a framework payload adds without turning the scan into a second traversal
# of the document. Running out of either says so — see _nested_record_list.
#
# The node budget is deliberately far above ``capture_json``'s ``max_records``
# default, and that is not slack. The first level of this scan is the list's own
# elements, so a budget below the record count runs out on every large feed, reports
# the scan incomplete, and costs a genuine 5,000-record census -- the very outcome
# the skip in _descend exists to protect. It only has to be high enough that running
# out means the document is pathological rather than merely big; the walk is over
# data already in memory and visits containers only, so a high ceiling costs nothing.
_WRAPPER_SCAN_DEPTH = 4
_WRAPPER_SCAN_NODES = 50_000

# What an embedded payload's own envelope calls the next page, and what it calls the
# size of the corpus.
#
# Read off the top-level object AND off a small closed set of named envelope blocks,
# because the two standardised paginated-JSON envelopes do not put either signal at the
# top level. JSON:API is ``{"data": [...], "links": {"next": ...}, "meta": {"total": N}}``
# and HAL is ``{"_links": {"next": {"href": ...}}}``; a top-level-only read censused page
# one of both. The set is closed rather than a document-wide scan for these words, which
# is what keeps a nav menu's ``{"nav": {"next": "/about"}}`` out -- "nav" is not an
# envelope block and never will be.
_NEXT_PAGE_KEYS = (
    "next",
    "next_page",
    "nextPage",
    "next_url",
    "nextUrl",
    "has_more",
    "hasMore",
    "hasNextPage",
    "more",
)
_STATED_TOTAL_KEYS = (
    "totalCount",
    "total_count",
    "totalRecords",
    "totalResults",
    "numberMatched",
    "recordCount",
    "numFound",
    "total",
    "count",
)

# A page COUNT above one says there are more pages whatever the row keys say, and it is
# the only signal ``{"page": 1, "pages": 7}`` gives.
_PAGE_COUNT_KEYS = (
    "pages",
    "page_count",
    "pageCount",
    "total_pages",
    "totalPages",
    "num_pages",
    "numPages",
    "last_page",
    "lastPage",
)

# And a page SIZE the walk exactly filled. ``{"offset": 0, "limit": 50}`` beside fifty
# rows is a full page, and a full page is the one thing a paginated endpoint always
# emits when there is more. It costs a census on a feed whose corpus happens to be
# exactly its own page size, which is a coincidence with a named escape hatch, against a
# false exact-count invariant which has neither.
_PAGE_SIZE_KEYS = ("limit", "per_page", "perPage", "page_size", "pageSize")

# Where an envelope hides when it is not at the top. One level of these is followed from
# the document, and one more from inside them (``{"meta": {"pagination": {...}}}``);
# past that the "closed set" argument stops holding and a scan is a scan.
_ENVELOPE_BLOCKS = (
    "links",
    "_links",
    "meta",
    "pagination",
    "paging",
    "page_info",
    "pageInfo",
)

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _RecordList:
    """A record list found in a document, and how much standing the find has.

    ``authoritative`` is True only when the source itself named the list and named
    exactly one — the difference between reading a feed and guessing at a document,
    and therefore the difference between a census and a count.

    ``basis`` is *why*, one of the ``RECORD_LIST_*`` constants. Withholding a census
    needs only the boolean; deciding whether a human has to look at the payload needs
    to know whether the search ran out of budget or actually found a rival, because
    the first still returns rows the source named. Appended last with a default so
    every existing construction keeps binding.
    """

    rows: list[Any]
    authoritative: bool
    basis: str = RECORD_LIST_NAMED


@dataclass
class _Walk:
    """One shape's traversal, before the census rule is applied to it."""

    paths: list[str] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)
    records: list[CapturedRecord] = field(default_factory=list)
    truncated: bool = False
    # A corpus size the source itself vouched for, when one is available.
    reported_total: int | None = None
    # False when the rows were found by a guess rather than named by the source: the
    # same fact that denies this walk a census, since knowing the corpus was captured
    # whole means knowing which list was the corpus.
    record_list_identified: bool = True
    record_list_basis: str = RECORD_LIST_NAMED
    pagination_kind: str = "single"
    pagination_detail: str | None = None


def capture_json(
    candidate: Candidate,
    client: HttpClient,
    session: CaptureSession,
    draft_dir: Path,
    out_dir: Path,
    *,
    page_size: int = 1000,
    max_records: int = 5000,
) -> CaptureResult:
    """Page the feed, and return the records to measure plus whether they are all of them.

    ``out_dir`` is where fixtures land; it must be the directory the session
    recorded as its ``fixtures_root``, since that is how the manifest locates the
    files it names. ``page_size`` is the rows asked for per request, clamped so the
    last request of a capped run asks only for what is left — overshooting would
    leave the fixture on disk holding records the result never counted.

    The sub-shape comes from ``candidate.channel``. ``page_type`` is not consulted:
    choosing between an HTML listing and an embedded payload is the caller's
    decision about which shape module to invoke, and by the time it lands here that
    choice has been made.
    """
    fixtures.check_fixture_root(session, draft_dir, out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    args = (candidate, client, session, draft_dir, out_dir, page_size, max_records)
    if candidate.channel is Channel.SOCRATA:
        walk = _walk_socrata(*args)
    elif candidate.channel is Channel.ARCGIS:
        walk = _walk_arcgis(*args)
    else:
        walk = _walk_embedded(*args)

    # The manifest and this result have to describe the same corpus, or a later pass
    # re-parsing the fixtures the manifest names finds records this count never
    # included.
    session_mod.keep_only(session, draft_dir, urls=walk.urls)

    return CaptureResult(
        listing_paths=walk.paths,
        detail_paths=[],
        records=walk.records,
        records_captured=len(walk.records),
        records_total=_total(walk),
        pagination_kind=walk.pagination_kind,
        pagination_detail=walk.pagination_detail,
        truncated=walk.truncated,
        record_list_identified=walk.record_list_identified,
        record_list_basis=walk.record_list_basis,
    )


def _total(walk: _Walk) -> int | None:
    """The corpus size, or None when this walk is not entitled to claim one.

    A source-reported total counts only while it stays *above* what was captured.
    One that comes back equal would hand a stopped-short capture the census marker,
    and one that comes back below it is a number this walk has already disproved.

    ``record_list_identified`` is the third gate, and it is about *authority* rather
    than completeness. A Socrata or ArcGIS census is earned: the feed says where its
    rows are and signals the end of its corpus with a short page or
    ``exceededTransferLimit: false``. An embedded payload says neither, so when its
    record list was picked out of a document by heuristic rather than named
    unambiguously by the source, the rows are still captured and the total withheld.
    """
    if walk.reported_total is not None and walk.reported_total > len(walk.records):
        return walk.reported_total
    if walk.records and not walk.truncated and walk.record_list_identified:
        return len(walk.records)
    return None


# --- Socrata SODA ---


def _walk_socrata(
    candidate: Candidate,
    client: HttpClient,
    session: CaptureSession,
    draft_dir: Path,
    out_dir: Path,
    page_size: int,
    max_records: int,
) -> _Walk:
    """Page ``$limit``/``$offset`` under ``$order=:id`` until the feed runs short.

    The order clause is not decoration. SODA does not promise a stable order across
    requests without one, so paging an unordered feed can return the same row twice
    and never return another at all — a corpus that is neither a census nor visibly
    short of one. ``:id`` is the system column every dataset has.

    ``$limit`` is a request, not a guarantee: a view with a server-side override, or
    a proxy in front of one, can answer with more rows than were asked for. What this
    capture holds in memory, counts, and hands downstream has to be bounded by the cap
    it was configured with rather than by whatever size a response happened to arrive
    at, so an over-long page is cut to the limit and ends the walk short.
    """
    walk = _Walk(pagination_kind="soda_offset", pagination_detail="$limit/$offset")
    base = _socrata_resource(candidate)
    seen: set[str] = set()
    fetched = 0

    while True:
        limit = min(page_size, max_records - fetched)
        if limit <= 0:
            # The cap, not the feed, ended this walk. Whatever is past it is
            # unmeasured, and how much of it there is nobody here knows.
            walk.truncated = True
            break
        url = f"{base}?$order=:id&$limit={limit}&$offset={fetched}"
        if url in seen:
            walk.truncated = True
            break
        seen.add(url)

        body = _fetch_page(client, session, draft_dir, out_dir, walk, url, ".json")
        rows = _as_list(body)
        if rows is None:
            # SODA answers a rejected query with an object, not the array it serves
            # rows in; a gateway answers with HTML. Either way the feed did not say
            # it was finished, so this is a walk cut short, not an ending — and the
            # body is not a page of this corpus, so it goes out of the walk with it.
            _discard_page(walk)
            walk.truncated = True
            break

        overflow = len(rows) > limit
        if overflow:
            walk.truncated = True
            rows = rows[:limit]

        fetched += len(rows)
        if not _add_records(walk, rows):
            break
        if overflow or len(rows) < limit:
            break  # a short page is SODA's end-of-feed signal

    return walk


def _socrata_resource(candidate: Candidate) -> str:
    """The ``/resource/{id}.json`` endpoint this dataset is served from.

    The dataset id came off a Scout discovery run, which is to say off a server.
    Percent-encoding it with nothing safe keeps it a single path segment, so a
    value carrying ``/`` or ``?`` cannot bolt a different endpoint or an extra
    query onto the URL this capture then fetches under the host allowlist.
    """
    if candidate.dataset_id is None:
        # Nothing to build from; the index URL is already the endpoint.
        return candidate.index_url.split("?", 1)[0]
    parsed = urlparse(candidate.index_url)
    dataset = quote(candidate.dataset_id, safe="")
    return f"{parsed.scheme}://{parsed.netloc}/resource/{dataset}.json"


# --- ArcGIS FeatureServer ---


def _walk_arcgis(
    candidate: Candidate,
    client: HttpClient,
    session: CaptureSession,
    draft_dir: Path,
    out_dir: Path,
    page_size: int,
    max_records: int,
) -> _Walk:
    """Page ``resultOffset``/``resultRecordCount`` until the layer stops saying there is more.

    ``exceededTransferLimit`` is the layer's own statement that it withheld rows, so
    it — not a short page — is what decides whether the walk has reached the end.
    A layer that keeps asserting it while returning nothing would page the same
    offset forever, and every one of those is a real request, so an offset that
    stops advancing ends the walk short rather than looping.
    """
    walk = _Walk(
        pagination_kind="arcgis_offset",
        pagination_detail="resultOffset/resultRecordCount",
    )
    base = _arcgis_query(candidate.index_url)
    seen: set[str] = set()
    fetched = 0

    while True:
        count = min(page_size, max_records - fetched)
        if count <= 0:
            walk.truncated = True
            break
        url = (
            f"{base}?where=1%3D1&outFields=*&f=json"
            f"&resultRecordCount={count}&resultOffset={fetched}"
        )
        if url in seen:
            walk.truncated = True
            break
        seen.add(url)

        body = _fetch_page(client, session, draft_dir, out_dir, walk, url, ".json")
        payload = _as_object(body)
        features = payload.get("features") if payload is not None else None
        if payload is None or not isinstance(features, list):
            # An error object, or a body that is not the query response at all. Not a
            # page of this corpus, so it leaves the walk along with the manifest.
            _discard_page(walk)
            walk.truncated = True
            break

        overflow = len(features) > count
        if overflow:
            # The layer served more than ``resultRecordCount`` asked for. Same rule as
            # SODA: the configured cap bounds this capture, not the response size.
            walk.truncated = True
            features = features[:count]

        fetched += len(features)
        if not _add_records(walk, features):
            break
        if overflow or not payload.get("exceededTransferLimit"):
            break  # the layer says it withheld nothing

    if walk.truncated:
        walk.reported_total = _arcgis_count(client, base)
    return walk


def _arcgis_query(index_url: str) -> str:
    """The layer's ``/query`` endpoint, whether or not the candidate already names it."""
    base = index_url.split("?", 1)[0].rstrip("/")
    if not base.endswith("/query"):
        base = f"{base}/query"
    return base


def _arcgis_count(client: HttpClient, base: str) -> int | None:
    """The layer's own record count, or None when it will not give one up.

    This is the one authoritative corpus size a sampled ArcGIS capture can get, and
    it is asked for only when the walk already knows it stopped short. The response
    is metadata about the corpus rather than a page of it, so it is deliberately
    not written as a fixture or recorded in the manifest — a manifest entry for it
    would put a non-record page into the set a later pass re-parses.

    A layer that 404s the probe, rate-limits it, or answers with something other
    than a count costs this capture a total and nothing more; the sample it already
    holds is still the sample it holds.
    """
    try:
        response = client.get(f"{base}?where=1%3D1&f=json&returnCountOnly=true")
        payload = _as_object(fixtures.decode(response.content))
    except Exception:
        _logger.warning("could not read a record count from %s; total stays unknown", base)
        return None
    count = payload.get("count") if payload is not None else None
    if isinstance(count, int) and not isinstance(count, bool):
        return count
    return None


# --- JSON embedded in a page ---


def _walk_embedded(
    candidate: Candidate,
    client: HttpClient,
    session: CaptureSession,
    draft_dir: Path,
    out_dir: Path,
    page_size: int,
    max_records: int,
) -> _Walk:
    """Take the payload out of one page; it is the whole corpus, or a known part, or a guess.

    There is no second request to make here, so the cap cannot hide anything: the
    full row list is in hand either way. Over the cap, that makes ``records_total``
    exactly right and the capture an explicitly scoped sample rather than a walk
    that ran out of budget mid-feed.

    All of which holds only while the list this walk found really is the source's
    record list. Socrata and ArcGIS never have to wonder — the feed says where its
    rows are and says when they run out — but an embedded payload is an arbitrary
    document, and ``data``, ``items``, ``results`` and ``value`` are as likely to be
    a filter dropdown or a nav menu as a case list. A census earned by guessing right
    is indistinguishable from one earned by guessing wrong, and the wrong one becomes
    an exact-count invariant that a parser scraping the nav menu satisfies. So when
    the list was picked rather than named, the rows are captured and the total is not
    claimed.
    """
    walk = _Walk()
    url = candidate.index_url
    body = _fetch_page(client, session, draft_dir, out_dir, walk, url, ".html")

    payload = _embedded_payload(body)
    found = _rows(payload)
    if found is None:
        # A 200 whose body holds no record list this module recognises. Nothing was
        # captured, and a total of zero would be an exact-count invariant of zero.
        #
        # This is also the far side of a distinction worth keeping. A document that
        # named an empty list — ``{"data": []}`` — said where its records live and
        # simply has none, and that is a source serving nothing. This one never said
        # where to look at all, and that is a source nobody has read yet. Both report
        # no total; only the second is unidentified.
        walk.record_list_identified = False
        walk.record_list_basis = RECORD_LIST_UNREADABLE
        return walk

    walk.record_list_identified = found.authoritative
    walk.record_list_basis = found.basis
    kept = [row for row in found.rows if isinstance(row, dict)]
    if len(kept) != len(found.rows):
        # Entries that are not objects are not records, and a count that quietly
        # skips them understates a corpus it would otherwise call a census.
        walk.truncated = True
    elif len(kept) > max_records and walk.record_list_identified:
        # The payload's own length is the size of the corpus only if this list is
        # the corpus. Off a guess it is just the length of something.
        walk.truncated = True
        walk.reported_total = len(kept)
    elif len(kept) > max_records:
        walk.truncated = True
    _read_the_envelope(walk, payload, len(kept))
    _add_records(walk, kept[:max_records])
    return walk


def _read_the_envelope(walk: _Walk, payload: Any, kept: int) -> None:
    """Believe the payload when it says this page is not the whole corpus.

    "There is no second request to make here" is true of a payload inside an HTML page
    and false of the plain JSON endpoints this sub-shape also covers, and a plain JSON
    endpoint paginates. ``{"totalCount": 307, "next": "/api/cases?page=2", "data":
    [...50 rows...]}`` used to come back as an authoritative census of 50 — the most
    dangerous of the false censuses, because the 50 rows are real records: locators
    match, coverage is real, the floors are real, and the exact-count invariant asserts
    50 against a 307-record source with nothing downstream able to see it.

    Four signals, any one of which ends the census: a next-page pointer, a stated total
    above the rows in hand, a page COUNT above one, and a page SIZE the rows exactly
    filled. Each is read from the document and from :data:`_ENVELOPE_BLOCKS` — a closed
    set of names, not a document-wide scan, which is what keeps a nav menu's
    ``{"nav": {"next": "/about"}}`` out while covering JSON:API (``links.next`` +
    ``meta.total``) and HAL (``_links.next.href``). Reading the top level alone closed
    the reproduced document and censused page one of both standards.

    Neither finding is followed. Fetching page 2 is a second request under a rate limit
    with no offset vocabulary agreed with this source; what is said instead is that the
    walk stopped while the source was still offering more, which is what ``truncated``
    means and what ``--accept-partial truncated`` is for.
    """
    blocks = _envelope_objects(payload)
    for block in blocks:
        if _says_there_is_another_page(block, kept):
            walk.truncated = True
            break
    stated = _stated_total(blocks)
    if stated is not None and stated > kept:
        walk.truncated = True
        if walk.reported_total is None or stated > walk.reported_total:
            walk.reported_total = stated


def _envelope_objects(payload: Any) -> list[dict[str, Any]]:
    """The document and the named envelope blocks inside it, two levels down at most.

    Two levels because ``{"meta": {"pagination": {"total": N}}}`` is ordinary and
    ``{"meta": {"meta": {"meta": ...}}}`` is not. Past that the closed-set argument that
    keeps a nav menu out stops holding, and a deeper walk is a document scan wearing a
    whitelist.
    """
    if not isinstance(payload, dict):
        return []
    blocks = [payload]
    for name in _ENVELOPE_BLOCKS:
        inner = payload.get(name)
        if not isinstance(inner, dict):
            continue
        blocks.append(inner)
        for deeper_name in _ENVELOPE_BLOCKS:
            deeper = inner.get(deeper_name)
            if isinstance(deeper, dict):
                blocks.append(deeper)
    return blocks


def _says_there_is_another_page(block: Mapping[str, Any], kept: int) -> bool:
    """True when this one envelope object states, by any of three routes, that more exist."""
    for key in _NEXT_PAGE_KEYS:
        if key in block and _points_at_another_page(block[key]):
            return True
    for key in _PAGE_COUNT_KEYS:
        pages = _as_count(block.get(key))
        if pages is not None and pages > 1:
            return True
    if kept > 0:
        for key in _PAGE_SIZE_KEYS:
            size = _as_count(block.get(key))
            if size is not None and size == kept:
                return True
    return False


def _points_at_another_page(value: Any) -> bool:
    """True when this envelope value says another page exists.

    ``null``, ``false``, an empty string and ``0`` are every way a feed says "this is
    the last page" while still emitting the key. A dict is HAL's
    ``{"next": {"href": ...}}``, which says it by being there at all.
    """
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (int, float)):
        return value > 0
    if isinstance(value, (list, dict)):
        return bool(value)
    return True


def _stated_total(blocks: Sequence[Mapping[str, Any]]) -> int | None:
    """The corpus size the envelope claims, or None when it claims none.

    First match wins, blocks in order and keys in order, so the document's own
    ``totalCount`` outranks a number found in ``meta`` and both outrank the deliberately
    last-placed ``total`` and ``count``, which are the two words most likely to mean
    something other than a record count.
    """
    for block in blocks:
        for key in _STATED_TOTAL_KEYS:
            if key in block:
                total = _as_count(block[key])
                if total is not None:
                    return total
    return None


def _as_count(value: Any) -> int | None:
    """``value`` as a whole non-negative number, or None when it is not one.

    Strings and floats are accepted because envelopes serialise counts as both --
    ``{"totalCount": "307"}`` and ``{"totalCount": 307.0}`` are the same statement as
    ``307``, and an int-only read censused page one of each. A float with a fraction is
    not a count of anything and is refused rather than truncated towards one.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        return int(value) if value.is_integer() and value >= 0 else None
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        return int(text) if text.isdigit() else None
    return None


def _embedded_payload(body: str) -> Any:
    """The JSON document a page carries, from the body itself or from a script tag.

    The body is tried first because the shape covers plain JSON endpoints as well as
    HTML pages — the NH DOJ documents API is one. Failing that, every script on the
    page is considered, and a script whose document *names* its record list wins
    outright over one this module would only be guessing about, whatever their order
    on the page. Among equals it is document order, so a script is never displaced by
    a later one of the same standing.
    """
    try:
        return json.loads(body)
    except ValueError:
        pass
    soup = BeautifulSoup(body, "html.parser")
    guess: Any = None
    guessed = False
    for script in soup.find_all("script"):
        text = script.get_text().strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except ValueError:
            continue
        found = _rows(payload)
        if found is None:
            continue
        if found.authoritative:
            return payload
        if not guessed:
            guess, guessed = payload, True
    return guess if guessed else None


# --- shared payload handling ---


def _fetch_page(
    client: HttpClient,
    session: CaptureSession,
    draft_dir: Path,
    out_dir: Path,
    walk: _Walk,
    url: str,
    suffix: str,
) -> str:
    """Fetch one page, file it under a counter-derived name, and note it on the walk."""
    name = fixtures.fixture_name(session, "page", len(walk.paths) + 1, url, suffix=suffix)
    name, body = fixtures.fetch(client, session, draft_dir, out_dir, url, name)
    walk.paths.append(name)
    walk.urls.append(url)
    return body


def _discard_page(walk: _Walk) -> None:
    """Take the page just fetched back out of the corpus this walk will report.

    A page is filed before its body can be classified, and some bodies turn out not
    to be pages of records at all — a SODA error envelope, a gateway's HTML, an
    ArcGIS error object. Leaving one in the walk leaves it in the manifest, and the
    manifest is what a later pass re-parses, so an error envelope would sit on disk
    beside the real pages and be read as one of them. The file itself stays where it
    is, exactly as ``keep_only`` leaves every fixture it stops naming.

    Only ever called immediately before the walk breaks, so the ordinal it frees up
    is never handed to another page.
    """
    walk.paths.pop()
    walk.urls.pop()


def _add_records(walk: _Walk, rows: list[Any]) -> bool:
    """Append the object rows of one page, and say whether the walk may continue.

    False means the page held something that is not a record. The rows that *were*
    objects are still kept — they are real captured data — but the walk is marked
    truncated and stops, because a count that silently omits the rest would be
    reported as the size of the whole corpus.
    """
    name = walk.paths[-1]
    kept = [row for row in rows if isinstance(row, dict)]
    for index, row in enumerate(kept):
        walk.records.append(
            CapturedRecord(
                key=f"{name}#{index}",
                payload=json.dumps(row, sort_keys=True),
                page="list",
            )
        )
    if len(kept) != len(rows):
        walk.truncated = True
        return False
    return True


def _as_list(body: str) -> list[Any] | None:
    """The JSON array this body is, or None if it is anything else."""
    try:
        payload = json.loads(body)
    except ValueError:
        return None
    return payload if isinstance(payload, list) else None


def _as_object(body: str) -> dict[str, Any] | None:
    """The JSON object this body is, or None if it is anything else."""
    try:
        payload = json.loads(body)
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


class _Decline(Enum):
    """Why the named search left part of a document unread.

    One member per kind of bound. Adding a bound means adding a member here, which is
    the point: the name has to be written down before the search can stop looking.
    """

    # A width or depth bound. The rest of the document is simply unread.
    BOUND = "bound"
    # The elements of a named list that holds records. Not structure, and not a place
    # a candidate can hide: a candidate is a list under a row key, and these are the
    # rows themselves.
    RECORDS = "records"


@dataclass
class _Survey:
    """The one record of what the named search chose not to read.

    ``authoritative`` is a claim about a *count* — this document named exactly one
    plausible record list — and a count is only as good as the search behind it. Three
    times now a bound has been added to this search that hid a candidate from the named
    scan and left one survivor looking unambiguous: a census of a nav menu, of a filler
    array, of a group wrapper. Each was introduced by the fix for the one before it,
    and each was a bound that did not know it had to say so.

    So every bound routes through :meth:`decline`, and the default there is that not
    looking means not knowing. A fourth bound added by someone who never read this
    docstring costs the search its completeness for free, which is the safe answer;
    exempting it is a deliberate act on one line, next to the reasoning for the only
    exemption that exists.
    """

    complete: bool = True

    def decline(self, reason: _Decline) -> None:
        """Record that part of the document will not be read, and what it costs.

        :attr:`_Decline.RECORDS` is the single vouched-for decline, because there is
        provably no candidate inside it. Everything else — including a reason added
        later — means the search cannot say how many candidates the document holds,
        and so cannot be authoritative about the one it found.
        """
        if reason is not _Decline.RECORDS:
            self.complete = False


def _rows(payload: Any) -> _RecordList | None:
    """The record list inside ``payload``, and whether the source named it or this did.

    Two searches, run strictly one after the other rather than interleaved by depth.

    First the *named* search: every list sitting under one of the known row keys,
    anywhere in the document down to the bounds, collected shallowest-first. Running
    it to exhaustion before anything else is what stops a shallow unrelated array
    from beating the feed's own ``data`` list — a payload shaped like
    ``{"nav": [...], "wrapper": {"data": [...]}}`` is ordinary, and picking ``nav``
    off it yields a census of the navigation menu.

    Only if that finds nothing does the *generic* search answer, with the shallowest
    non-empty list of objects it saw. That is a guess, and it is marked as one.

    So is a named search that turned up more than one *plausible* candidate. The
    vocabulary is fixed and its words are common — ``items``, ``results``, ``value``
    and ``data`` name filter dropdowns and nav menus at least as often as they name
    case lists — so two live matches mean the document did not settle the question
    and neither can this. Only lists that could actually be records count towards
    that: an empty list and a list of scalars are disqualified as answers already, so
    letting them create ambiguity would cost real censuses while protecting nothing.
    A document naming exactly one plausible list still earns its census however many
    empty ``items`` arrays sit beside it.

    A search that hit either bound is not authoritative *whatever* it found, and that
    is load-bearing rather than tidy. The bounds truncate a level, a truncated level
    can drop a rival candidate, and one survivor of a truncation looks exactly like a
    document that only ever named one. Voiding authority is what stops a width limit
    from manufacturing the census the two searches above exist to prevent.

    The walk descends through arrays as well as objects, since a record list wrapped
    in one (``{"a": [{"data": [...]}]}``) is otherwise invisible to the named search.
    It stops only at a named list whose elements really are records, because walking
    those would spend the whole width budget on the very feed whose census is at
    stake — see :func:`_holds_a_record_list` for why "named" alone is not enough.

    Returning a find with no usable rows is not the same as returning nothing. A
    document that named an empty list said where its records live and has none; a
    document this search could not read never said where to look. Both end up
    reporting an unknown total, and the caller carries the difference into
    ``record_list_identified``.
    """
    if isinstance(payload, list):
        # The document *is* the list. There is nothing to search and nothing to
        # choose between, so this is the one find that needs no name behind it.
        return _RecordList(rows=payload, authoritative=True)

    survey = _Survey()
    named: list[list[Any]] = []
    guess: list[Any] | None = None
    level: list[Any] = [payload]
    budget = _MAX_PAYLOAD_NODES
    depth = 0

    while True:
        nodes = [node for node in level if isinstance(node, dict)]
        if not nodes:
            break  # the document ran out before the bounds did: a complete search
        if depth >= _MAX_PAYLOAD_DEPTH or len(nodes) > budget:
            survey.decline(_Decline.BOUND)
            break
        budget -= len(nodes)
        depth += 1
        for node in nodes:
            for key in _ROW_KEYS:
                value = node.get(key)
                if isinstance(value, list):
                    named.append(value)
        if guess is None:
            guess = _first_record_list(nodes)
        level = _descend(nodes, survey)

    contenders = [candidate for candidate in named if _looks_like_records(candidate)]
    if contenders:
        chosen = contenders[0]
        basis = _basis(survey, len(contenders))
        authoritative = survey.complete and len(contenders) == 1
        if authoritative and _outranked_by_something_inside_it(chosen):
            # One contender, and it wraps a longer list. Descending found no rival
            # because the inner list is not named by a word in the vocabulary, so
            # nothing else here will catch it: this is the last place the group-wrapper
            # census can be refused. The rows are still returned — they are real objects
            # — but they are groups, and counting groups is not a census.
            authoritative, basis = False, RECORD_LIST_WRAPPED
        return _RecordList(rows=chosen, authoritative=authoritative, basis=basis)
    if named:
        # The source named where its records live; there just are not any this
        # capture can measure in there. Still an identified record list.
        return _RecordList(
            rows=named[0],
            authoritative=survey.complete and len(named) == 1,
            basis=_basis(survey, len(named)),
        )
    if guess is not None:
        return _RecordList(rows=guess, authoritative=False, basis=RECORD_LIST_GUESSED)
    return None


def _basis(survey: _Survey, matches: int) -> str:
    """Why a find is or is not authoritative, in the caller's vocabulary.

    Ambiguity is reported ahead of an incomplete search, because it is the stronger
    statement: a document that named two plausible lists did not settle the question
    however much of it was read, while a document that named one settled it for the
    part that *was* read. The order matters to a consumer deciding whether a person
    has to look — genuine ambiguity always does, an exhausted budget may not.
    """
    if matches > 1:
        return RECORD_LIST_AMBIGUOUS
    return RECORD_LIST_NAMED if survey.complete else RECORD_LIST_BOUNDED


def _descend(nodes: list[dict[str, Any]], survey: _Survey) -> list[Any]:
    """The next level down: every value of these objects, and every element of a list.

    Except a named list that holds records, which is skipped. Flattening a few
    thousand case objects onto the next level would exhaust the width budget and cost
    the document the authority it had just earned, and nothing is down there anyway:
    the records ARE the leaves of this search.

    A named list holding *wrappers* is a different object entirely and is walked. The
    two are told apart by :func:`_holds_a_record_list`, and the direction of that
    judgement matters more than its accuracy: descending too eagerly can only spend
    budget, and spending budget costs a census, while skipping too eagerly hides a
    rival candidate and manufactures one.

    That skip is a bound like the width and depth ones, so it is declared to the
    survey rather than taken quietly. It is the only bound exempt from costing the
    search its completeness, and :class:`_Survey` is where that exemption is argued.
    """
    below: list[Any] = []
    for node in nodes:
        for key, value in node.items():
            if isinstance(value, list):
                if key in _ROW_KEY_SET and not _holds_a_record_list(value):
                    survey.decline(_Decline.RECORDS)
                    continue
                below.extend(value)
            else:
                below.append(value)
    return below


def _holds_a_record_list(candidate: list[Any]) -> bool:
    """True when this list's elements look like wrappers around records, not records.

    A record is a leaf — its fields are scalars and small things — while a group or page
    wrapper carries the actual record list somewhere inside it. So an element holding
    anything that could itself be a record list marks the whole list as structure to
    walk through rather than rows to stop at.

    NOT one level deep, and that was a real false census: ``{"data": [{"page": {"cases":
    [...120...]}}]}`` puts the inner list under an intermediate object, so a scan of the
    element's own values sees only a dict, calls the list records, skips it, and hands
    the document an authoritative census of one wrapper. ``__NEXT_DATA__`` payloads are
    the same shape one level deeper again. :func:`_nested_record_list` searches the
    element to :data:`_WRAPPER_SCAN_DEPTH`.

    Deliberately generous. A record that happens to carry a nested array of objects —
    aliases, agencies, related cases — reads as a wrapper here, and the search descends
    into a list it did not need to. That costs width budget, and running out of budget
    costs a census. The opposite mistake, calling a wrapper list a record list, hides
    whatever the wrapper holds from the named search and hands the document an
    authoritative census of its wrappers. One of those is recoverable by an operator
    and the other is a false exact-count invariant, so the bias goes this way.
    """
    size, complete = _nested_record_list(candidate)
    return size > 0 or not complete


def _outranked_by_something_inside_it(candidate: list[Any]) -> bool:
    """True when a list nested inside these elements is LONGER than this list is.

    The second half of the group-wrapper defence, and the half that does not need the
    inner list to sit under a row key. Descending into a wrapper only helps when the
    named search then finds the real list by name; ``{"data": [{"page": 1, "entries":
    [...120...]}]}`` calls its inner list ``entries``, which is not in the vocabulary, so
    the descent finds no rival and the outer list of one wrapper is still the only
    contender — an authoritative census of one.

    A list cannot be a document's record list while one of its own elements holds a
    longer one. That is the comparison, and it is deliberately a comparison rather than
    a flat "holds anything nested": a genuine 120-record feed whose records each carry
    two aliases has nested record-like lists in every element, and voiding its census
    for that would cost real captures to protect against nothing. Only the inversion —
    a short outer list wrapping a long inner one — is the group-wrapper shape.

    An incomplete scan counts as outranked. Not looking is not evidence.
    """
    size, complete = _nested_record_list(candidate)
    return size > len(candidate) or not complete


def _nested_record_list(candidate: list[Any]) -> tuple[int, bool]:
    """The longest record-like list nested inside these elements, and whether we saw it all.

    Returns ``(0, True)`` for a list of plain records. The boolean is False when the scan
    hit its depth or node budget, which both callers read as the unsafe answer: a search
    that stopped looking cannot be the evidence that there is nothing there.
    """
    longest = 0
    budget = _WRAPPER_SCAN_NODES
    level: list[Any] = [element for element in candidate if isinstance(element, dict)]
    for _ in range(_WRAPPER_SCAN_DEPTH):
        if not level:
            return (longest, True)
        if len(level) > budget:
            return (longest, False)
        budget -= len(level)
        below: list[Any] = []
        for node in level:
            values = node.values() if isinstance(node, dict) else node
            for value in values:
                if _looks_like_records(value):
                    longest = max(longest, len(value))
                if isinstance(value, (dict, list)):
                    below.append(value)
        level = below
    return (longest, not level)


def _first_record_list(nodes: list[dict[str, Any]]) -> list[Any] | None:
    """The first list of objects among these nodes' values, in key order."""
    for node in nodes:
        for value in node.values():
            if _looks_like_records(value):
                return list(value)
    return None


def _looks_like_records(value: Any) -> bool:
    """True for an unnamed list this module is willing to guess is the record list.

    Every element has to be an object, and there has to be at least one. A list of
    strings or numbers is a tag list, a facet, or an id column, and an empty list is
    no evidence at all — reading either as the records would produce a confident
    count of the wrong thing.
    """
    return isinstance(value, list) and bool(value) and all(isinstance(i, dict) for i in value)
