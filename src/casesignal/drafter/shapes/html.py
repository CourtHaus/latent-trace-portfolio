"""Capture an HTML source: every listing page, a spanning sample of detail pages.

The two halves are deliberately asymmetric. Listing pages are walked
*exhaustively* — no cap — because the listing corpus is what a later pass
asserts the parser's record count against, and a listing captured up to page 4
of 9 turns that invariant into a lie. Detail pages are *sampled*, because
fetching hundreds of them from a rate-limited government site is not viable and
field coverage does not need all of them. The sample spans the listing rather
than taking its first rows: sources are routinely ordered by surname, and a
head-biased sample measures the letter A.

A source whose fields all live on the listing captures no detail pages at all
and takes its records from the listing markup. That is the Oklahoma OSBI shape —
inline teaser blocks with no per-case URLs — and it is normal, not an error.

"No cap" is not "no termination condition". A CMS pager that renders its next
link unconditionally past the last page emits a fresh URL forever, and every one
of them is a real rate-limited GET, so the walk also stops on the first page that
yields no records. But stopping there is not the same as reaching the end: an
outage block or an interstitial parses to nothing while still linking the page
after it, and a walk that halts on one has captured part of a listing. Nothing
here can tell those two apart from the markup, so a walk that stopped while the
source was still offering more says so — ``truncated``, and no total. The same
goes for a pager that cycles: a live next link pointing back at a page already
captured leaves whatever follows it unreachable, whether that is nothing (a
disabled next rendered as the current page) or half the listing. A capture that
parsed nothing at all is the same move once more: an *unknown* total rather than
a total of zero, because captured == total is what marks a census downstream, and a
census of zero is an exact-count invariant that every parser passes.

Two more ways a walk can stop for a reason the source never gave, both closed the
same way — a census has to be positive evidence that the walk finished, never the
absence of evidence that it did not. A pager outside the three-selector vocabulary
(``a.pagination__next``, ``a[aria-label="Next"]``, a bare numbered pager) is
invisible to ``_next_link``, so "we found no next link" used to end the walk
indistinguishably from "the source said there is no next page"; the page that ends a
walk is now checked for a forward affordance still pointing somewhere unvisited, and
one found there is ``truncated``. And a listing whose rows are outside the record
vocabulary but whose whole list sits inside one ``<article>`` matched the generic
fallback, returning the container as a single record: twelve rows reported as a census
of one, which the inventory then endorsed by scoring every locator 1/1 against the
wrapper. A capture whose records came from the generic fallback AT ALL now says
``record_list_identified=False`` with basis ``wrapped``, and the census gate here
carries that third condition the way :func:`json_feed._total` always has. Counting the
matches cannot separate the two cases -- a wrapper beside a sidebar promo is two matches
and still not two records -- so the condition is which selector won, not how many nodes
it returned.

Fetching, naming, and resuming fixtures is not specific to HTML and lives in
:mod:`casesignal.drafter.shapes.fixtures`, which owns the rules that keep a
resumed page the page it claims to be. What is this module's own is the corpus:
fixtures for URLs the walk no longer reaches are dropped from the manifest at
the end, so what the manifest names and what the result counts are the same set
of pages.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from casesignal.drafter import session as session_mod
from casesignal.drafter.session import CaptureSession
from casesignal.drafter.shapes import fixtures
from casesignal.drafter.shapes.base import (
    RECORD_LIST_NAMED,
    RECORD_LIST_WRAPPED,
    CapturedRecord,
    CaptureResult,
    HttpClient,
)
from casesignal.drafter.shapes.fixtures import FixtureRootMismatch, UnsafeFixturePath
from casesignal.etl.services.bs_helpers import attr_str
from casesignal.scout.models import Candidate, Page

# Tried in order; the first selector that matches anything wins the page, so the
# order is most specific first. ``article`` is last because it is the one generic
# wrapper here: a page that wraps its whole list in a single <article> would
# otherwise return that wrapper as ONE record and report it as a census of one.
_RECORD_SELECTORS = ("a.case", "li.case", "div.cmp-teaser", "article")

# The last entry of _RECORD_SELECTORS, named so the walk can tell "the source's own
# record class matched" from "nothing matched and we fell back to the page's article".
# Ordering ``article`` last only helps when an EARLIER selector matches; when the rows
# use markup outside the vocabulary (``div.case-row``, ``tr.case``, ``div.views-row``)
# and the list sits inside one <article>, the fallback is the only hit and it returns
# the wrapper as one record. See _record_nodes.
_GENERIC_RECORD_SELECTOR = _RECORD_SELECTORS[-1]

_NEXT_SELECTORS = ("a.next", "a[rel='next']", "li.pager__item--next a")

# Pagination this module cannot WALK but can still SEE. _NEXT_SELECTORS is the
# vocabulary the walk follows; a pager outside it (``a.pagination__next``,
# ``a[aria-label="Next"]``, ``li.next > a``, a bare numbered pager) used to end the walk
# indistinguishably from a source saying "there is no next page", which is a census over
# page 1 of n. These selectors are never followed -- following an arbitrary link found
# this way is how a walk wanders off the listing -- they only answer whether the page
# that ended the walk was still offering more.
_FORWARD_HINT_SELECTORS = (
    "a[rel~='next']",
    "a[class*='next' i]",
    "a[id*='next' i]",
    "a[aria-label*='next' i]",
    "a[title*='next' i]",
    "[class*='next' i] a[href]",
    "[id*='next' i] a[href]",
)

# A forward affordance that carries no class, id or aria at all: the link is just the
# word or the glyph. Compared against the anchor's whole stripped text, lower-cased.
_FORWARD_HINT_TEXTS = frozenset({"\u00bb", "\u203a", "\u2192", ">", ">>"})

# Pagination containers, for the one case a forward affordance cannot cover: a pager
# rendered as page numbers with no next link. Only consulted on a walk that never
# followed a next link at all -- see _more_on_offer for why the same check on the last
# page of a walked pager would refuse every correctly finished listing.
_PAGER_CONTAINER_SELECTORS = (
    "[class*='pagination' i]",
    "[class*='pager' i]",
    "[class*='paging' i]",
    "[id*='pagination' i]",
    "[id*='pager' i]",
    "nav[aria-label*='pag' i]",
)

# Where a record with no link of its own might carry the id detail_url_pattern wants.
_ID_ATTRS = ("data-case-id", "data-id", "id")

_FETCHABLE_SCHEMES = ("http", "https")

# Re-exported: both are raised from inside capture_html, so callers catching them
# should not have to know which module the shared machinery lives in.
__all__ = ["FixtureRootMismatch", "UnsafeFixturePath", "capture_html"]


def capture_html(
    candidate: Candidate,
    client: HttpClient,
    session: CaptureSession,
    draft_dir: Path,
    out_dir: Path,
    *,
    detail_sample: int = 12,
) -> CaptureResult:
    """Walk the listing, sample detail pages, and return the records to measure.

    ``out_dir`` is where fixtures land; it must be the directory the session
    recorded as its ``fixtures_root``, since that is how the manifest locates the
    files it names. ``detail_sample`` is an upper bound — a listing shorter than
    the sample is captured whole.
    """
    fixtures.check_fixture_root(session, draft_dir, out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    listing_paths: list[str] = []
    listing_urls: list[str] = []
    records: list[CapturedRecord] = []
    next_selector: str | None = None
    truncated = False
    wrapped = False

    url: str | None = candidate.index_url
    seen: set[str] = set()
    while url is not None:
        seen.add(url)
        name = fixtures.fixture_name(
            session, "listing", len(listing_paths) + 1, url, suffix=".html"
        )
        name, html = fixtures.fetch(client, session, draft_dir, out_dir, url, name)
        soup = BeautifulSoup(html, "html.parser")
        listing_paths.append(name)
        listing_urls.append(url)
        nodes, matched_by = _record_nodes(soup)
        if matched_by == _GENERIC_RECORD_SELECTOR:
            # The generic fallback WON, which is the whole condition. Every selector
            # that names the source's own record markup missed, so whatever <article>
            # matched is <article> doing its ordinary job -- a page container, a sidebar
            # promo, a header block -- as often as it is a record, and nothing in the
            # markup says which. The rows ARE captured, so this is not an empty capture;
            # what it cannot be is a count.
            #
            # This used to also require ``len(nodes) == 1``, which closed the reproduced
            # document and left its nearest neighbour open: a wrapper PLUS a sidebar
            # promo is two <article> matches, and a 12-record listing came back
            # ``captured=2 total=2`` -- the same false census one theme element away.
            # Counting matches cannot tell a wrapper from a record; only the vocabulary
            # can, and here the vocabulary is what failed.
            wrapped = True
        for index, node in enumerate(nodes):
            records.append(
                CapturedRecord(
                    key=f"{name}#{index}",
                    payload=str(node),
                    page="list",
                    detail_url=_detail_url(candidate, node, url),
                )
            )
        found = _next_link(soup, url)
        if not nodes:
            # Out of records. Either the pager ran past its end, or this page is an
            # interstitial the source still links past; the markup does not say
            # which, so stopping here means the corpus may be short.
            truncated = found is not None or _more_on_offer(
                soup, url, seen, walked_a_pager=next_selector is not None
            )
            url = None
        elif found is None:
            # No next link this walk knows how to follow. That is the source saying
            # "this is the last page" only if there is no pagination here at all, or
            # none that still points somewhere unvisited. Absence of a recognised next
            # link is not evidence of the end of the listing.
            truncated = _more_on_offer(soup, url, seen, walked_a_pager=next_selector is not None)
            url = None
        elif found[0] in seen:
            # A live next link pointing back at a page already captured. Following it
            # would loop forever, and not following it leaves anything past the cycle
            # unreachable — which may be nothing (a disabled next rendered as the
            # current page) or may be half the listing. Nothing here can tell.
            truncated = True
            url = None
        else:
            url, next_selector = found

    detail_paths: list[str] = []
    if _needs_detail(candidate):
        targets = _detail_targets(records)
        for position in _sample_indices(len(targets), detail_sample):
            index = targets[position]
            target = records[index]
            detail_url = target.detail_url
            if detail_url is None:  # unreachable: _detail_targets only yields linked records
                continue
            name = fixtures.fixture_name(
                session, "detail", len(detail_paths) + 1, detail_url, suffix=".html"
            )
            name, payload = fixtures.fetch(client, session, draft_dir, out_dir, detail_url, name)
            detail_paths.append(name)
            records[index] = CapturedRecord(
                key=target.key,
                payload=payload,
                page="detail",
                detail_url=detail_url,
            )

    # The manifest and this result have to describe the same corpus, or a later
    # pass re-parsing the fixtures the manifest names finds records this count
    # never included.
    session_mod.keep_only(
        session,
        draft_dir,
        urls=seen | {r.detail_url for r in records if r.detail_url is not None},
    )

    kind, detail = _pagination(listing_urls, next_selector)
    identified = not wrapped
    return CaptureResult(
        listing_paths=listing_paths,
        detail_paths=detail_paths,
        records=records,
        records_captured=len(records),
        # A census only when the walk actually reached the end of the listing AND the
        # things counted are records: captured == total is what marks one downstream.
        # Nothing parsed is not a census of zero, a walk that stopped while the source
        # was still offering more is not a census of what it happened to reach, and one
        # container holding the whole list is not a census of one. The third gate mirrors
        # json_feed._total, which has always had it — an accepted finding must not hand
        # back the census the finding was about.
        records_total=len(records) if records and not truncated and identified else None,
        pagination_kind=kind,
        pagination_detail=detail,
        truncated=truncated,
        record_list_identified=identified,
        record_list_basis=RECORD_LIST_NAMED if identified else RECORD_LIST_WRAPPED,
    )


def _detail_targets(records: Sequence[CapturedRecord]) -> list[int]:
    """Positions of the records a detail page can actually be fetched for.

    Records with no link are filtered out *before* sampling rather than skipped
    during it: a skipped sample slot is a fetch nobody makes, so a listing where
    half the records carry no href would quietly halve the denominator the detail
    coverage floor is computed over. Records sharing one detail URL collapse to
    their first, since fetching that page twice would weight it double in exactly
    the same measurement.
    """
    targets: list[int] = []
    claimed: set[str] = set()
    for index, record in enumerate(records):
        if record.detail_url is None or record.detail_url in claimed:
            continue
        claimed.add(record.detail_url)
        targets.append(index)
    return targets


def _record_nodes(soup: BeautifulSoup) -> tuple[list[Tag], str | None]:
    """Records on one listing page, and the selector that found them.

    The selector comes back because which one won is a fact about how much the match
    is worth. ``a.case``, ``li.case`` and ``div.cmp-teaser`` are the source's own record
    markup; ``article`` is a fallback that matches the page's container just as happily
    as a record, and the caller needs to be able to tell those apart.
    """
    for selector in _RECORD_SELECTORS:
        nodes = soup.select(selector)
        if nodes:
            return (list(nodes), selector)
    return ([], None)


def _more_on_offer(
    soup: BeautifulSoup, base_url: str, seen: set[str], *, walked_a_pager: bool
) -> bool:
    """True when the page that ended the walk still pointed at a listing page nobody read.

    Positive evidence that the walk stopped short, not the absence of evidence that it
    finished. Three passes, narrowest first:

    1. A forward affordance outside :data:`_NEXT_SELECTORS` — ``a.pagination__next``,
       ``a[aria-label="Next"]``, ``li.next > a`` — resolving somewhere unvisited.
    2. The same thing with no attributes at all: an anchor whose whole text is the word
       "next" or a forward glyph.
    3. Only on a walk that never followed a next link: any link inside a pagination
       container resolving somewhere unvisited, which is the numbered-pager-with-no-next
       case.

    The third pass is deliberately not run on a walk that DID page. The last page of an
    ordinary pager links back to "1" and "First", and the first page was entered at the
    bare index URL (``/cases``) rather than at the URL the pager gives it
    (``/cases?page=0``), so those backward links resolve outside ``seen`` on every
    correctly finished listing. Scoping the pass to unwalked pagers is what keeps the
    check from refusing the exact Drupal shape ``li.pager__item--next a`` exists for.

    Never used to CONTINUE the walk. Following a link matched this loosely is how a
    walk wanders off the listing into a site's footer; the only thing said here is that
    the corpus may be short.
    """
    for selector in _FORWARD_HINT_SELECTORS:
        for node in soup.select(selector):
            if _unfollowed(node, base_url, seen):
                return True
    for node in soup.select("a[href]"):
        text = node.get_text(strip=True).lower()
        if (text.startswith("next") or text in _FORWARD_HINT_TEXTS) and _unfollowed(
            node, base_url, seen
        ):
            return True
    if walked_a_pager:
        return False
    for selector in _PAGER_CONTAINER_SELECTORS:
        for container in soup.select(selector):
            for node in container.select("a[href]"):
                if _unfollowed(node, base_url, seen):
                    return True
    return False


def _unfollowed(node: Tag, base_url: str, seen: set[str]) -> bool:
    """True when this anchor points at a fetchable page the walk never captured."""
    target = _fetchable(attr_str(node, "href"), base_url)
    return target is not None and target not in seen


def _next_link(soup: BeautifulSoup, base_url: str) -> tuple[str, str] | None:
    """The next listing page and the selector that found it, or None at the end."""
    for selector in _NEXT_SELECTORS:
        for node in soup.select(selector):
            href = attr_str(node, "href")
            target = _fetchable(href, base_url)
            if target is not None:
                return target, selector
    return None


def _needs_detail(candidate: Candidate) -> bool:
    """True only when detail pages exist *and* the inventory says a field is on one.

    A ``detail_url_pattern`` on its own is not a reason to spend requests: if every
    field the Scout found lives on the listing, the detail pages hold nothing this
    capture is measuring.
    """
    if candidate.detail_url_pattern is None:
        return False
    return any(spec.page == Page.DETAIL for spec in candidate.fields.values())


def _detail_url(candidate: Candidate, node: Tag, listing_url: str) -> str | None:
    """Where this record's detail page lives, or None when it has none.

    The record's own link wins, resolved against the listing URL it was found on:
    it is what the site itself says, so it survives ids that are not in the URL and
    patterns the Scout guessed slightly wrong. ``detail_url_pattern`` is the
    fallback for records that carry no link at all — the pattern's ``{id}`` is
    filled from the record's id attribute, percent-encoded so a value from the page
    cannot restructure the URL.
    """
    href = attr_str(node, "href") if node.name == "a" else None
    if href is None:
        inner = node.select_one("a[href]")
        href = attr_str(inner, "href") if inner is not None else None
    resolved = _fetchable(href, listing_url)
    if resolved is not None:
        return resolved

    pattern = candidate.detail_url_pattern
    if pattern is None:
        return None
    record_id = _record_id(node)
    if record_id is not None:
        pattern = pattern.replace("{id}", quote(record_id, safe=""))
    if "{" in pattern:  # an unfilled placeholder is not a URL
        return None
    return _fetchable(pattern, listing_url)


def _record_id(node: Tag) -> str | None:
    """The record's own id, from the attributes a listing block plausibly carries."""
    for attr in _ID_ATTRS:
        value = attr_str(node, attr)
        if value is not None and value.strip():
            return value.strip()
    return None


def _fetchable(href: str | None, base_url: str) -> str | None:
    """Resolve ``href`` against ``base_url``, or None if it is not something to GET.

    Filters out the anchors that are not pages: empty hrefs, bare fragments, and
    ``mailto:`` / ``javascript:`` links, all of which appear in listing markup.
    """
    if href is None or not href.strip():
        return None
    resolved = urljoin(base_url, href.strip())
    if urlparse(resolved).scheme not in _FETCHABLE_SCHEMES:
        return None
    return resolved


def _sample_indices(count: int, sample: int) -> list[int]:
    """Positions of an evenly spaced sample of ``count`` records, endpoints included.

    Spacing is over the whole listing, not a fixed stride from the front: on an
    alphabetically ordered source a head-biased sample measures one letter's worth
    of records and calls it coverage. A sample at least as large as the listing
    takes everything.
    """
    if count <= 0 or sample <= 0:
        return []
    if sample >= count:
        return list(range(count))
    if sample == 1:
        return [0]
    step = (count - 1) / (sample - 1)
    return [round(position * step) for position in range(sample)]


def _pagination(listing_urls: Sequence[str], selector: str | None) -> tuple[str, str | None]:
    """How the listing paged, and the selector that found the link, for the drafter.

    ``query_param`` when the pages differ only in query string (``?page=2``),
    ``path`` when the page number is in the path (``/cases/page/2``). The adapter
    the drafter writes has to reproduce whichever it was.
    """
    if len(listing_urls) < 2:
        return "single", None
    first, second = urlparse(listing_urls[0]), urlparse(listing_urls[1])
    kind = "query_param" if first.path == second.path else "path"
    return kind, selector
