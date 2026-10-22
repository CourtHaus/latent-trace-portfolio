"""Capture orchestration: the gate, the client, the route, and the brief.

Everything downstream of a capture measures what this module let through. The
shape modules know how to walk a listing or page a feed; none of them knows
whether the candidate was ever supposed to be walked, which shape it is, or
whether what came back is fit to hand to an inventory pass. That is this module,
and it is the only place those questions are asked.

*The gate.* A candidate is refused before a single request when it is not
``ACCEPTED``, when either hard gate is not ``PASS``, when it needs JavaScript,
when its ``page_type`` says PDF, or when its index URL is not ``https``. These
are scope refusals: the source is outside what v1 can draft, and no amount of
retrying changes that.

*The route.* No shape module reads ``page_type`` — :func:`capture_json` says so in
its own docstring and hands the decision here. ``channel`` picks the transport
(``SOCRATA`` and ``ARCGIS`` are feeds, ``WEB`` is a page) and ``page_type`` picks
the ``WEB`` sub-shape: a page whose records live in a JSON payload is captured as
embedded JSON, anything else as an HTML listing. Where the two disagree — a feed
channel whose ``page_type`` says HTML — the candidate is refused rather than
routed on a guess, because the wrong route does not fail loudly: it captures a
document nobody meant and measures it.

*The client.* Exactly one host — the candidate's — is added to the allowlist, and
no robots bypass is passed at all, not even the ambient one
``CASESIGNAL_BYPASS_ROBOTS_HOSTS`` would supply. A bypass is a per-source operator
decision that belongs in a run-book, and a draft capture that silently inherited
one from a shell would hide the very thing the draft is supposed to discover.
Everything else about :class:`~casesignal.etl.services.polite_http.PoliteHTTPClient`
stands untouched: IP literals, private and reserved ranges, DNS rebinding, and
redirect hops are all refused independently of what this module allowlists.

*The transport.* Arkansas is the lesson: a source verified with curl while the
adapter ran httpx, and the Cloudflare TLS-fingerprint block was not found until
ingest day. So a 403 that looks like a fingerprint block retries the whole capture
once with ``tls_impersonate=True`` and records ``transport="curl_cffi"`` — the
adapter is drafted against the transport that actually works.

*The refusal policy on what came back.* Four results are captured successfully
and are still not fit to draft against, and each is a refusal here rather than a
surprise later:

- **No records.** A capture with an empty corpus measures nothing. Coverage over
  zero records is not a low number, it is no number, and every floor derived from
  it is vacuous. The usual cause is a listing outside the shape module's selector
  vocabulary, which is an operator's problem and not a source's.
- **A truncated walk.** Worse than an empty one, because it looks like data. The
  safety-critical half is already handled upstream (a truncated walk reports no
  total, so the exact-count invariant cannot fire), but a parser drafted against
  a corpus that stopped at a cyclic pager reproduces the stop and nobody sees it.
- **A record list nobody can point at.** Rows measured without knowing which list
  in the document holds the records. The inventory would then measure the wrong
  objects and report a thin source rather than an unidentified one, and those two
  need very different responses.
- **A corpus the source's own published count disagrees with.** The one check here
  that does not come out of the walk. Every other refusal asks the walk whether it
  believes it finished; this one asks the number Source Scout recorded off the source
  itself, and a stated 307 against a corpus of 1, 2 or 50 is a second witness. It is
  what the spec asks for (`design.md:352-355`) and it backstops every way a walk can
  stop for a reason the source never gave, including ways nobody has enumerated. How
  far short is allowed depends on how the Scout came by the number: none for an EXACT
  count out of a catalog, half for one read off a page that said "over 300".

Each raises :class:`IncompleteCapture`, which carries the outcome so a caller can
tell the operator what landed on disk. The fixtures stay; a re-run resumes them.

The third of those is *not* the whole of ``record_list_identified=False``, and the
difference is the difference between refusing a source and refusing a source's nav
menu. That flag goes false for four reasons and ``CaptureResult.record_list_basis``
says which: a document that named two plausible lists, one that named none, and one
that named nothing readable are all a person's problem; a document search that spent
its width or depth budget is not. The last one still holds rows the source itself
named — a large unrelated array beside the record list is enough to cause it — so it
costs the *census*, which the shape module already withholds, and nothing else. It
is logged here and the capture stands.

Because no candidate field names a record list, and because a listing whose next link
points at a page already captured is often a complete one-page listing with a disabled
pager, all three findings can be accepted by name through ``accept_partial``. Nothing
is accepted by default; every acceptance is logged and recorded in ``brief.json``, so
it travels with the artefact rather than living in one operator's shell history. An
error-status fixture has no name there: the bytes are the server's refusal, and no
operator decision turns them into records.

*The corpus.* ``keep_only`` prunes the manifest to the URLs a walk still reaches
and the shape modules discard what it returns, so a resumed capture whose source
changed shape drops fixtures with nothing said. This module diffs the manifest
across the walk: a partial prune is logged and carried on the outcome, and a prune
that took the entire previous corpus is refused — a session whose every fixture
was replaced is a different capture wearing an old session's id.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from casesignal.drafter import session as session_mod
from casesignal.drafter.session import CaptureSession
from casesignal.drafter.shapes.base import (
    RECORD_LIST_AMBIGUOUS,
    RECORD_LIST_BOUNDED,
    RECORD_LIST_GUESSED,
    RECORD_LIST_UNREADABLE,
    RECORD_LIST_WRAPPED,
    CaptureResult,
    HttpClient,
)
from casesignal.drafter.shapes.html import capture_html
from casesignal.drafter.shapes.json_feed import capture_json
from casesignal.etl.services.polite_http import DisallowedHost
from casesignal.scout.models import (
    Candidate,
    CaptureInfo,
    Channel,
    Confidence,
    GateResult,
    Status,
)

_logger = logging.getLogger(__name__)

_BRIEF = "brief.json"

# Politer than a production ingest by default: a draft capture walks an entire
# listing on a government host that has never seen us before.
_RATE_LIMIT_SECONDS = 2.0

# The only form of ``now`` this module accepts. ``session.start`` folds unsafe
# characters out of the id it builds, but the id is also what an operator types
# and greps for, so it is kept filename-safe at source rather than repaired after.
# Anchored with ``\Z`` and matched with ``fullmatch``: ``$`` matches *before* a
# trailing newline, so "2026-08-31T14:02:11Z\n" would otherwise pass a check whose
# entire job is to keep a session id filename-safe.
_NOW_FORM = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")

# Shapes. These strings are the session's ``shape``, ``CaptureInfo.shape``, and
# the brief's ``shape`` — one vocabulary, set here and nowhere else.
SHAPE_HTML = "html"
SHAPE_SOCRATA = "socrata"
SHAPE_ARCGIS = "arcgis"
SHAPE_EMBEDDED = "embedded_json"

_CHANNEL_FEED_SHAPES = {Channel.SOCRATA: SHAPE_SOCRATA, Channel.ARCGIS: SHAPE_ARCGIS}

# ``page_type`` is a free string written by the classifier, so it is read by token
# rather than matched exactly. A JSON token wins over an HTML one: an embedded
# payload lives inside a page, so "html_embedded_json" is a JSON source described
# by where it hides, not a contradiction.
# The routing tokens are matched at token boundaries, not as substrings: "capias"
# contains "api", and a wrong route is the single failure this router is built to
# avoid. An underscore is a boundary here (``\b`` treats it as a word character), so
# "api_json" and "html_embedded_json" still match while "capias" and "webpager" do not.
_JSON_TOKENS = ("json", "api", "feed", "geojson")
_HTML_TOKENS = ("html", "page", "listing", "table", "index")

# The PDF stem is deliberately NOT bounded, and the asymmetry is the point. The two
# gates fail in opposite directions. A routing token matched too loosely sends a
# source to the wrong shape module, which captures a document nobody meant and
# measures it — silent, and the thing boundaries exist to prevent. The PDF check is a
# *refusal*, so matching it too loosely costs a refusal an operator can see and argue
# with, while matching it too tightly drafts a source this pipeline has no shape
# module for. "pdfs_table", "table_of_pdfs" and "scanned_pdfs_page" are all a page
# whose records are PDFs, and no English word this classifier would emit contains
# "pdf" as an accident — unlike "api" inside "capias" or "feed" inside "feedback".
#
# The other reading, that a listing whose rows carry PDF links is legitimately an
# HTML capture, is true only when the fields live in the HTML rows, and page_type is
# a free string that cannot say which. So this gate stays conservative: capture what
# we can prove we can draft, and refuse loudly otherwise. (DC MPDC, a real PDF
# source, is exactly the shape being kept out.)
_PDF_TOKENS = ("pdf",)


def _token_pattern(tokens: tuple[str, ...]) -> re.Pattern[str]:
    joined = "|".join(tokens)
    return re.compile(rf"(?<![a-z0-9])({joined})(?![a-z0-9])")


_PDF_PATTERN = re.compile("|".join(_PDF_TOKENS))
_JSON_PATTERN = _token_pattern(_JSON_TOKENS)
_HTML_PATTERN = _token_pattern(_HTML_TOKENS)

# What an operator may accept about a capture that would otherwise be refused. Named
# rather than boolean, so an acceptance says which finding it forgives and travels
# into the brief as that name; nothing here is on by default.
ACCEPT_EMPTY = "empty"
ACCEPT_TRUNCATED = "truncated"
ACCEPT_UNIDENTIFIED = "unidentified"
ACCEPT_COUNT_MISMATCH = "count_mismatch"
ACCEPTABLE = frozenset({ACCEPT_EMPTY, ACCEPT_TRUNCATED, ACCEPT_UNIDENTIFIED, ACCEPT_COUNT_MISMATCH})

# How far the corpus this capture holds may fall below the count the Scout recorded,
# as a fraction of that count, by how the Scout came by it.
#
# EXACT gets no slack, and it is worth being exact about what EXACT is, because it is
# NOT "a number a catalog vouched for". ``scout/estimate.py`` sets it two ways: from a
# catalog/API row count, which only Socrata and ArcGIS candidates have, and — for a WEB
# candidate, which is the shape this drafter meets most often, the ONLY route — from a
# regex over page-1 HTML matching "<a> to <b> of <N>" or "of <N> results|cases|records|
# entries". So on the ordinary source this is a string scraped at scout time and frozen
# there: it can count a superset (solved cases included), it can have drifted between
# scout and draft, and it can have matched something that was never a case count.
#
# Zero tolerance stands anyway, and for a reason that survives that: this is the rung
# where the source published a specific number rather than an impression, so a
# disagreement with it is the strongest evidence available from outside the walk — and
# the consequence is a named, visible, acceptable refusal, while the alternative is a
# false exact-count invariant nothing downstream can see. What must not be claimed is
# that the number was authoritative; only that disagreeing with it is worth stopping for.
#
# PROBED is a count inferred from paging behaviour; VISIBLE was read off the page, where
# "over 300 cold cases" is the house style and an undercount is normal. A confidence
# this module has not heard of takes the loosest tolerance rather than the tightest: an
# unknown provenance is weak evidence, and weak evidence should not manufacture refusals.
_COUNT_TOLERANCE: dict[Confidence | None, float] = {
    Confidence.EXACT: 0.0,
    Confidence.PROBED: 0.25,
    Confidence.VISIBLE: 0.5,
}
_DEFAULT_COUNT_TOLERANCE = 0.5

# An adapter name, however it was arrived at. Same shape the generated ones take,
# because it names a Python package, a YAML key, and a line in the pipeline registry.
# Matched with ``fullmatch`` for the reason above: under ``match`` and ``$``,
# "cold_case_ok\n" is accepted and becomes a source key reading "cold_case_ok\n_2026_08_31".
_ADAPTER_NAME_FORM = re.compile(r"[a-z][a-z0-9_]*")

# And bounded. The name is a path component in several generated files — the package
# directory, ``test_<name>_expectations.py`` — so an unbounded one runs past the
# 255-byte filename limit somewhere downstream rather than here. The longest name in
# the repo is 29 characters; this leaves room without leaving the question open.
_ADAPTER_NAME_MAX = 64

_STOPWORDS = frozenset({"of", "the", "and", "for", "a", "an", "at", "in", "on"})
_NON_SLUG = re.compile(r"[^0-9a-z]+")

# What a TLS-fingerprint block says when it 403s. Header evidence is checked first
# because it survives a body we could not decode.
_BLOCK_HEADERS = ("cf-ray", "cf-mitigated", "x-akamai-transformed")
_BLOCK_MARKERS = (
    "just a moment",
    "attention required",
    "cloudflare",
    "enable javascript and cookies",
    "you have been blocked",
    "ddos protection",
    "access denied",
    "incapsula",
    "perimeterx",
)

ClientFactory = Callable[..., HttpClient]


class Refused(Exception):
    """Raised when a capture must not be run, or must not be handed downstream."""


class IncompleteCapture(Refused):
    """Raised when a capture ran but what it produced is not fit to draft against.

    Carries the :class:`CaptureOutcome` so a caller can report what did land — the
    fixtures are on disk and named by the manifest, and a re-run resumes them.
    """

    def __init__(self, message: str, outcome: CaptureOutcome) -> None:
        self.outcome = outcome
        super().__init__(message)


@dataclass(frozen=True)
class CaptureOutcome:
    """One capture run: what it produced, in which session, as which shape.

    ``transport`` is the transport that actually worked — ``curl_cffi`` when a TLS
    fingerprint block forced impersonation — and is recorded so the drafted adapter
    is written for the transport the source answers.

    ``dropped_urls`` names fixtures the walk no longer reaches, pruned from the
    manifest during this run. Empty on a first capture; non-empty means the source
    changed under a resumed session.
    """

    result: CaptureResult
    session: CaptureSession
    shape: str
    # Appended last with defaults so the brief's three-field construction still binds.
    transport: str = "httpx"
    dropped_urls: tuple[str, ...] = ()


# --- identity ---


def adapter_name_for(candidate: Candidate, *, override: str | None = None) -> str:
    """The stable adapter identity: ``cold_case_<state>_<agency>``.

    The agency half is its acronym where the name offers one — parenthesised
    (``... (OSBI)``), already capitalised (``Minnesota BCA``), or derivable from the
    initials of three or more significant words (``Arkansas State Police`` -> ASP).
    Shorter names keep their words. The result is what names the package, keys the
    YAML entry, and decides whether a re-run replaces an entry or appends one, so it
    must not carry a capture date; :func:`source_key_for` is where the date goes.

    ``override`` is the operator's, and it wins. No rule reproduces the names already
    in the repo: where the state is the first significant word its initial lands in
    the acronym as well as in the ``cold_case_<state>_`` prefix (``wy_wdci`` against
    the repo's ``wy_dci``, ``oh_oag`` against ``oh_ag``), and the repo is not
    consistent about that, so a better rule cannot exist — only a way to say the
    name. Because the name is identity, renaming after the fact means renaming a
    package, a YAML key, and a pipeline registration together; the override is here
    so that never has to happen.
    """
    if override is not None:
        return _checked_adapter_name(override, "adapter name")
    state = _slug(candidate.state)
    agency = _agency_slug(candidate.agency)
    derived = f"cold_case_{state}_{agency}" if agency else f"cold_case_{state}"
    # The derived name is checked too. The constraint belongs to the name, not to who
    # supplied it: a candidate carrying a runaway agency string produces a package
    # directory just as unusable as one an operator typed.
    return _checked_adapter_name(derived, "adapter name derived from the candidate")


def _checked_adapter_name(name: str, described: str) -> str:
    """Return ``name``, or refuse it as something that cannot name a package."""
    if not _ADAPTER_NAME_FORM.fullmatch(name):
        raise Refused(
            f"{described} {name!r} is not a Python identifier in the house form "
            f"(lowercase, digits, underscores, leading letter, nothing else — a "
            f"trailing newline included); it names a package directory, a YAML key, "
            f"and a registry line."
        )
    if len(name) > _ADAPTER_NAME_MAX:
        raise Refused(
            f"{described} {name!r} is {len(name)} characters, over the "
            f"{_ADAPTER_NAME_MAX}-character limit; it is a path component in every "
            f"file the scaffold generates."
        )
    return name


def source_key_for(candidate: Candidate, capture_date: str, *, override: str | None = None) -> str:
    """The versioned source key: the adapter name plus the capture date."""
    return f"{adapter_name_for(candidate, override=override)}_{capture_date.replace('-', '_')}"


def _agency_slug(agency: str | None) -> str:
    """The agency half of an adapter name.

    An acronym the name already carries wins, whether it is parenthesised or not:
    parentheses are stripped before the words are read, so "... (OSBI)" and
    "Minnesota BCA" take the same branch. Reading the parenthesised text as a unit
    instead would be worse rather than more specific -- "Baltimore County Police
    Department (Homicide)" would name itself after the parenthetical.
    """
    if agency is None or not agency.strip():
        return ""
    words = _significant_words(agency)
    for word in words:
        if len(word) >= 2 and word.isupper() and word.isalpha():
            return _slug(word)
    if len(words) >= 3:
        return _slug("".join(word[0] for word in words))
    return _slug("_".join(words[:2]))


def _significant_words(name: str) -> list[str]:
    """The words that carry meaning, punctuation stripped, order preserved."""
    words: list[str] = []
    for raw in name.replace("(", " ").replace(")", " ").split():
        word = "".join(ch for ch in raw if ch.isalnum())
        if word and word.lower() not in _STOPWORDS:
            words.append(word)
    return words


def _slug(text: str) -> str:
    return _NON_SLUG.sub("_", text.lower()).strip("_")


# --- routing ---


def route(candidate: Candidate) -> str:
    """The shape this candidate is captured as, or a refusal when nothing is decisive.

    ``channel`` picks the transport and ``page_type`` picks the ``WEB`` sub-shape.
    A feed channel described as an HTML page is a contradiction between the two
    fields, and the wrong branch of it captures a document nobody meant, so it is
    refused rather than resolved in favour of either.
    """
    hint = _page_type_hint(candidate.page_type)
    feed_shape = _CHANNEL_FEED_SHAPES.get(candidate.channel)
    if feed_shape is not None:
        if hint == "html":
            raise Refused(
                f"candidate {candidate.id} has channel {candidate.channel.value} but "
                f"page_type {candidate.page_type!r}; the channel says feed and the "
                f"page_type says HTML page, and routing on either would capture the "
                f"other one's source. Fix the candidate before capturing."
            )
        return feed_shape
    if hint == "json":
        return SHAPE_EMBEDDED
    if hint in ("html", "none"):
        return SHAPE_HTML
    raise Refused(
        f"candidate {candidate.id} has page_type {candidate.page_type!r}, which names "
        f"neither an HTML page nor a JSON payload; refusing to guess which shape "
        f"module to capture it with."
    )


def _page_type_hint(page_type: str | None) -> str:
    """Classify a free-text ``page_type`` into none / html / json / pdf / unknown."""
    if page_type is None or not page_type.strip():
        return "none"
    text = page_type.lower()
    if _PDF_PATTERN.search(text):
        return "pdf"
    if _JSON_PATTERN.search(text):
        return "json"
    if _HTML_PATTERN.search(text):
        return "html"
    return "unknown"


# --- capture ---


def capture(
    candidate: Candidate,
    *,
    draft_dir: Path,
    fixtures_dir: Path,
    client_factory: ClientFactory,
    now: str,
    nonce: str,
    detail_sample: int = 12,
    session_id: str | None = None,
    refresh: bool = False,
    adapter_name: str | None = None,
    accept_partial: Iterable[str] = (),
) -> CaptureOutcome:
    """Gate the candidate, build the client, run the shape, and write ``brief.json``.

    ``now`` must be ``YYYY-MM-DDTHH:MM:SSZ``; the session id is built from it and is
    used as a filename component. ``session_id`` resumes a named session and refuses
    if the draft directory holds another one — the explicit-resume path a CLI
    ``--session-id`` flag drives. Without it a manifest already in ``draft_dir`` is
    continued and its absence starts a session; ``refresh`` starts one regardless.

    ``adapter_name`` overrides the derived identity. ``accept_partial`` names which of
    the quality refusals the operator has decided to accept for this source —
    ``ACCEPT_EMPTY``, ``ACCEPT_TRUNCATED``, ``ACCEPT_UNIDENTIFIED``,
    ``ACCEPT_COUNT_MISMATCH`` — and is empty by
    default, because an acceptance defaulted on is not a gate. Every acceptance is
    logged and recorded in ``brief.json``, so it travels with the artefact rather than
    living in one operator's shell history.
    """
    accepted = _check_acceptances(accept_partial)
    _check_scope(candidate)
    shape = route(candidate)
    host = _check_url(candidate)
    _check_now(now)
    name = adapter_name_for(candidate, override=adapter_name)
    fixtures_root = _fixtures_root(draft_dir, fixtures_dir)

    impersonate = bool(candidate.tls_impersonate_needed)
    client = _build_client(client_factory, host, impersonate=impersonate)
    session = _open_session(
        draft_dir,
        shape,
        now=now,
        nonce=nonce,
        fixtures_root=fixtures_root,
        session_id=session_id,
        refresh=refresh,
    )

    before = {fixture.url for fixture in session.fixtures}
    try:
        result = _run_shape(candidate, client, session, draft_dir, fixtures_dir, detail_sample)
    except Exception as exc:  # broad on purpose: re-raised unless it is the TLS block
        if impersonate or not _looks_like_a_fingerprint_block(exc):
            raise
        _logger.warning(
            "capture of %s was refused with a 403 that looks like a TLS fingerprint "
            "block; retrying the whole capture over curl_cffi. The drafted adapter "
            "will be written for that transport.",
            candidate.index_url,
        )
        impersonate = True
        client = _build_client(client_factory, host, impersonate=True)
        session = session_mod.start(
            draft_dir, shape, now=now, nonce=nonce, fixtures_root=fixtures_root
        )
        before = set()
        result = _run_shape(candidate, client, session, draft_dir, fixtures_dir, detail_sample)

    dropped = sorted(before - {fixture.url for fixture in session.fixtures})
    outcome = CaptureOutcome(
        result=result,
        session=session,
        shape=shape,
        transport="curl_cffi" if impersonate else "httpx",
        dropped_urls=tuple(dropped),
    )
    _check_corpus(outcome, before, dropped)
    _check_result(outcome, candidate, accepted)
    write_brief(
        draft_dir,
        build_brief(candidate, outcome, now=now, adapter_name=name, accepted=accepted),
    )
    return outcome


def _run_shape(
    candidate: Candidate,
    client: HttpClient,
    session: CaptureSession,
    draft_dir: Path,
    fixtures_dir: Path,
    detail_sample: int,
) -> CaptureResult:
    """Dispatch to the shape module the session was opened for.

    A second-host source (the ``media.ark.org`` shape: a listing on one host linking
    detail pages or assets on another) is refused by the client, correctly — this
    module allowlists one host on purpose. But ``DisallowedHost``'s message offers two
    remedies that are both inert on this path: ``allowed_hosts`` is passed explicitly,
    so the constructor branch that consults ``_DEFAULT_ALLOWED_HOSTS`` and
    ``CASESIGNAL_HTTP_EXTRA_HOSTS`` (polite_http.py:186-190) is never taken. Sending
    an operator down two dead ends for an expected outcome is worse than the refusal
    itself, so it is re-raised as a ``Refused`` naming the host and what actually
    changes it.
    """
    try:
        if session.shape == SHAPE_HTML:
            return capture_html(
                candidate, client, session, draft_dir, fixtures_dir, detail_sample=detail_sample
            )
        return capture_json(candidate, client, session, draft_dir, fixtures_dir)
    except DisallowedHost as exc:
        raise Refused(
            f"capture of {candidate.index_url} reached a host outside the one this "
            f"run allowlisted ({exc}). A draft capture allowlists exactly the "
            f"candidate's index host, so a source whose records or assets live on a "
            f"second host is out of scope for it — the environment variables that "
            f"message names are not consulted here. Split the source, or capture the "
            f"host that actually serves the records."
        ) from exc


# --- the gate ---


def _check_scope(candidate: Candidate) -> None:
    """Refuse a candidate v1 must not draft, before anything touches the network."""
    if candidate.status is not Status.ACCEPTED:
        raise Refused(
            f"candidate {candidate.id} has status {candidate.status.value}; only an "
            f"accepted candidate is captured."
        )
    gates = candidate.gates
    if gates is None or (
        gates.cold_homicide is not GateResult.PASS
        or gates.official_first_party is not GateResult.PASS
    ):
        cold = gates.cold_homicide.value if gates else "missing"
        official = gates.official_first_party.value if gates else "missing"
        raise Refused(
            f"candidate {candidate.id} has not passed both hard gates "
            f"(cold_homicide={cold}, official_first_party={official}); capture is "
            f"refused until both read pass."
        )
    if candidate.needs_js:
        raise Refused(
            f"candidate {candidate.id} needs JavaScript to render its records; v1 "
            f"captures static responses only."
        )
    if _page_type_hint(candidate.page_type) == "pdf":
        raise Refused(
            f"candidate {candidate.id} has page_type {candidate.page_type!r}; PDF "
            f"sources are out of scope for the drafter."
        )


def _check_now(now: str) -> None:
    """Refuse a timestamp that is not filename-safe, and one that is not a date.

    Two checks, because neither implies the other. The pattern is what keeps ``.``
    and ``+`` out of a session id used as a filename component; ``strptime`` is what
    keeps ``2026-13-45T99:99:99Z`` — correctly shaped, not a moment in time — out of
    a ``source_key`` that would then read ``cold_case_ok_osbi_2026_13_45``.
    """
    if not _NOW_FORM.fullmatch(now):
        raise Refused(
            f"capture timestamp {now!r} is not the required YYYY-MM-DDTHH:MM:SSZ form; "
            f"fractional seconds and a +00:00 offset both put characters into the "
            f"session id that are not safe in a filename."
        )
    try:
        datetime.strptime(now, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise Refused(
            f"capture timestamp {now!r} is correctly shaped but is not a real "
            f"instant ({exc}); it would name a session and date a source key."
        ) from exc


def _check_acceptances(accept_partial: Iterable[str]) -> frozenset[str]:
    """Normalise the operator's acceptances, refusing any name that means nothing."""
    accepted = frozenset(accept_partial)
    unknown = sorted(accepted - ACCEPTABLE)
    if unknown:
        raise Refused(
            f"accept_partial names {', '.join(unknown)}, which is not a finding this "
            f"capture can produce. The acceptable names are "
            f"{', '.join(sorted(ACCEPTABLE))}."
        )
    return accepted


def _check_url(candidate: Candidate) -> str:
    """Return the one host this capture may reach, refusing anything but https."""
    parsed = urlparse(candidate.index_url)
    if parsed.scheme != "https":
        raise Refused(
            f"candidate {candidate.id} has index_url {candidate.index_url!r}; capture "
            f"requires an https scheme."
        )
    host = parsed.hostname
    if not host:
        raise Refused(
            f"candidate {candidate.id} has index_url {candidate.index_url!r} with no host"
        )
    return host.lower()


def _build_client(factory: ClientFactory, host: str, *, impersonate: bool) -> HttpClient:
    """Build the run's client: one host allowlisted, no robots bypass, ever.

    ``bypass_robots_hosts`` is passed explicitly empty rather than left to default.
    Omitting it would let ``CASESIGNAL_BYPASS_ROBOTS_HOSTS`` out of the operator's
    shell decide robots policy for a source nobody has reviewed yet, and a bypass
    that is not in the run-book is a bypass nobody knows was taken.
    """
    return factory(
        rate_limit_seconds=_RATE_LIMIT_SECONDS,
        allowed_hosts=frozenset({host}),
        bypass_robots_hosts=frozenset(),
        tls_impersonate=impersonate,
    )


def _fixtures_root(draft_dir: Path, fixtures_dir: Path) -> str:
    """The fixtures directory as a path relative to the draft directory.

    The session stores this verbatim and validates nothing, and the manifest is
    what a later pass reads fixture paths out of, so the containment check belongs
    here — before a session records a root that points anywhere on the disk. The
    comparison is on resolved paths, so a symlinked fixtures directory pointing out
    of the draft directory is refused as well as an explicit ``..``.
    """
    root = draft_dir.resolve()
    target = fixtures_dir.resolve()
    if target == root:
        return ""
    if root not in target.parents:
        raise Refused(
            f"fixtures directory {fixtures_dir} resolves to {target}, outside the "
            f"draft directory {root}; the manifest would name fixtures it does not own."
        )
    return target.relative_to(root).as_posix()


# --- sessions ---


def _open_session(
    draft_dir: Path,
    shape: str,
    *,
    now: str,
    nonce: str,
    fixtures_root: str,
    session_id: str | None,
    refresh: bool,
) -> CaptureSession:
    """Start, resume, or continue the session this capture belongs to.

    ``session_id`` is the reachable path to :func:`session.resume`'s mismatch guard:
    an operator naming a session gets it checked against the one on disk. Without a
    named id the guard would be tautological — the id would come from the manifest
    we just read — so this is deliberately the only call to ``resume``.
    """
    if refresh:
        return session_mod.start(
            draft_dir, shape, now=now, nonce=nonce, fixtures_root=fixtures_root
        )
    existing = (
        session_mod.resume(draft_dir, session_id)
        if session_id is not None
        else session_mod.load(draft_dir)
    )
    if existing is None:
        return session_mod.start(
            draft_dir, shape, now=now, nonce=nonce, fixtures_root=fixtures_root
        )
    if existing.shape != shape:
        raise Refused(
            f"draft directory {draft_dir} holds session {existing.session_id} captured "
            f"as {existing.shape!r}, but this candidate routes to {shape!r}. The "
            f"manifest is pruned by URL, so one session holds one shape; pass "
            f"--refresh to start a new session."
        )
    if existing.fixtures_root != fixtures_root:
        raise Refused(
            f"session {existing.session_id} records fixtures_root "
            f"{existing.fixtures_root!r}, but this capture would write to "
            f"{fixtures_root!r}; resuming would measure fixtures the manifest does "
            f"not locate. Pass --refresh to start a new session."
        )
    return existing


# --- the refusal policy ---


def _check_corpus(outcome: CaptureOutcome, before: set[str], dropped: list[str]) -> None:
    """Surface, or refuse, fixtures this run pruned out of the manifest."""
    if not dropped:
        return
    if before and len(dropped) == len(before):
        raise IncompleteCapture(
            f"session {outcome.session.session_id} held {len(before)} fixture(s) and "
            f"this capture reached none of them, so the whole previous corpus was "
            f"dropped from the manifest. That is a different capture under an old "
            f"session id — check the index_url, then pass --refresh.",
            outcome,
        )
    _logger.warning(
        "session %s dropped %d fixture(s) from its manifest: the walk no longer "
        "reaches %s. The files stay on disk and nothing downstream counts them, but "
        "the source changed under a resumed session.",
        outcome.session.session_id,
        len(dropped),
        ", ".join(dropped),
    )


def _check_result(outcome: CaptureOutcome, candidate: Candidate, accepted: frozenset[str]) -> None:
    """Refuse a capture that ran but cannot honestly be measured.

    An error-status fixture is never acceptable and has no name in ``ACCEPTABLE``:
    the bytes are the server's refusal, and no operator decision turns them into
    records. The other three are findings about a corpus that does exist, and an
    operator who has looked at it may accept any of them by name.
    """
    result = outcome.result
    errored = [f for f in outcome.session.fixtures if f.status >= 400]
    if errored:
        raise IncompleteCapture(
            f"capture of {candidate.index_url} recorded {len(errored)} fixture(s) with "
            f"an error status ({errored[0].url} -> {errored[0].status}); those bytes "
            f"are the server's refusal, not records.",
            outcome,
        )
    if not result.record_list_identified:
        _judge_record_list(outcome, candidate, accepted)
    if result.records_captured == 0:
        _refuse_or_accept(
            outcome,
            accepted,
            ACCEPT_EMPTY,
            f"capture of {candidate.index_url} produced no records. Coverage over an "
            f"empty corpus is not a low number, it is no number, and every floor "
            f"derived from it would be vacuous. The usual cause is a listing outside "
            f"the shape module's selector vocabulary.",
        )
    if result.truncated:
        _refuse_or_accept(
            outcome,
            accepted,
            ACCEPT_TRUNCATED,
            f"capture of {candidate.index_url} stopped while the source was still "
            f"offering more, after {len(result.listing_paths)} page(s) and "
            f"{result.records_captured} record(s). A parser drafted against a "
            f"truncated corpus reproduces the stop, and nothing downstream can see "
            f"that it did. A listing whose next link points back at a page already "
            f"captured lands here too, and that one is often a complete one-page "
            f"listing with a disabled pager — check the fixtures before accepting it.",
        )
    _check_against_the_stated_count(outcome, candidate, accepted)


def _check_against_the_stated_count(
    outcome: CaptureOutcome, candidate: Candidate, accepted: frozenset[str]
) -> None:
    """Corroborate the corpus against the count the source itself published.

    ``design.md`` asks for exactly this: the listing-level record count "checked against
    the source's stated total where one exists". Until now ``case_count`` was written
    into ``brief.json`` and read by nothing.

    It is the cheapest corroboration there is, and it is the only one that comes from
    OUTSIDE the walk. Every other check in this module asks the walk whether it thinks
    it finished; a Scout-recorded count of 307 against a corpus of 1, 2 or 50 is a
    second source disagreeing, and it backstops every way a walk can stop for a reason
    the source never gave — including ways nobody has thought of yet.

    Only a corpus SHORT of the count refuses. Over-capturing is warned about and allowed
    to stand: a listing that also carries solved cases or unidentified-remains records is
    ordinary and is a question for the transform, while every false census this pipeline
    has produced under-counted.
    """
    count = candidate.case_count
    if count is None or count.value is None or count.value <= 0:
        return
    stated = count.value
    result = outcome.result
    # The corpus, not the sample: an ArcGIS layer answering returnCountOnly and an
    # embedded payload larger than the cap both report a total ABOVE what they captured,
    # and that total is the number the stated count is a statement about.
    corpus = result.records_total if result.records_total is not None else result.records_captured
    tolerance = _COUNT_TOLERANCE.get(count.confidence, _DEFAULT_COUNT_TOLERANCE)
    slack = stated * tolerance
    if corpus > stated + slack:
        _logger.warning(
            "capture of %s holds %d record(s) against a stated count of %d (%s). A "
            "listing that also carries solved or unidentified-remains records is the "
            "usual cause; the corpus stands and the transform is where that is decided.",
            candidate.index_url,
            corpus,
            stated,
            count.basis or "no basis recorded",
        )
        return
    if corpus >= stated - slack:
        return
    _refuse_or_accept(
        outcome,
        accepted,
        ACCEPT_COUNT_MISMATCH,
        f"capture of {candidate.index_url} holds a corpus of {corpus} record(s), but "
        f"Source Scout recorded this source as having {stated} "
        f"({count.confidence.value if count.confidence else 'unknown'} confidence; "
        f"{count.basis or 'no basis recorded'}). Two sources disagree about "
        f"how big this source is, and the capture is the one that can be wrong quietly: "
        f"a walk that stopped at an unrecognised pager, a listing whose rows fell outside "
        f"the shape module's vocabulary, or a paginated JSON endpoint read one page deep "
        f"all land here, and every one of them would otherwise be reported as a census "
        f"that a generated exact-count invariant then passes. Read the fixtures under "
        f"{outcome.session.fixtures_root or 'the draft directory'}; if the source's own "
        f"number is the stale one, this is the finding to accept.",
    )


def _judge_record_list(
    outcome: CaptureOutcome, candidate: Candidate, accepted: frozenset[str]
) -> None:
    """Refuse a record list nobody can point at; warn about one nobody finished reading.

    ``record_list_identified`` is False for four different reasons and only two of
    them are an operator's problem. A search that exhausted its width or depth budget
    declines to be authoritative *whatever* it found — that is what stops a bound from
    manufacturing a census — but the rows it holds were still named by the source. A
    document with six hundred nav objects beside its ``results`` list produces exactly
    that: the right records, refused for the nav menu's sake. Withholding the census
    is the correct consequence and json_feed already does it; refusing the capture is
    not, and there is no candidate field an operator could set to answer it.
    """
    result = outcome.result
    # Fail closed: only the one basis that is explicitly a spent search budget is
    # downgraded to a warning. A basis this module has not heard of -- a fifth reason
    # added to json_feed later -- refuses, which is the direction Task 6's survey
    # docstring argues for and the direction that costs a capture rather than a corpus.
    if result.record_list_basis == RECORD_LIST_BOUNDED:
        _logger.warning(
            "capture of %s searched the payload as far as its width and depth bounds "
            "allowed and stopped there, so it cannot claim the %d record(s) it holds "
            "are the only list the document names. The records are the ones the source "
            "named and are kept; the census is withheld (records_total is None). A "
            "large unrelated array beside the record list is the usual cause.",
            candidate.index_url,
            result.records_captured,
        )
        return
    if result.record_list_basis == RECORD_LIST_AMBIGUOUS:
        detail = (
            f"the payload named more than one plausible record list, and the "
            f"{result.records_captured} object(s) measured here are one of them"
        )
    elif result.record_list_basis == RECORD_LIST_WRAPPED:
        detail = (
            f"the {result.records_captured} object(s) measured here are wrappers around "
            f"the records rather than the records themselves -- an HTML listing whose "
            f"whole list sits inside one generic container, or a JSON list whose element "
            f"holds a longer list a level below. Counting them counts groups"
        )
    elif result.record_list_basis == RECORD_LIST_GUESSED:
        detail = (
            f"no list under any known record key was found, so the "
            f"{result.records_captured} object(s) measured here are simply the "
            f"shallowest list of objects in the document"
        )
    elif result.record_list_basis == RECORD_LIST_UNREADABLE:
        detail = "no record list was found in the payload at all, by name or by guess"
    else:
        detail = (
            f"the capture reported basis {result.record_list_basis!r}, which this "
            f"refusal policy does not recognise"
        )
    _refuse_or_accept(
        outcome,
        accepted,
        ACCEPT_UNIDENTIFIED,
        f"capture of {candidate.index_url} could not identify which list holds the "
        f"records: {detail}. An inventory over them would report a thin source rather "
        f"than an unidentified one. Read the captured payload under "
        f"{outcome.session.fixtures_root or 'the draft directory'}: if the rows are "
        f"right, this is the finding to accept.",
    )


def _refuse_or_accept(
    outcome: CaptureOutcome, accepted: frozenset[str], finding: str, message: str
) -> None:
    """Raise, unless the operator named this finding as one they have accepted.

    The remedy is appended HERE rather than written into each message, so all four
    refusals name the flag and the exact token, and none of them can drift from the
    constant that is actually checked. Every one of them used to end "accept the finding
    by name" without ever writing the name: the flag and its four tokens lived in the
    module docstring, in ``--help`` and in the run-book, and nowhere in the sentence the
    operator was actually reading. A remedy an operator cannot act on from the message
    that requires it is the same defect as a remedy that does not exist.
    """
    if finding not in accepted:
        raise IncompleteCapture(f"{message} {accept_hint(finding)}", outcome)
    _logger.warning("accepted %r on an otherwise refused capture: %s", finding, message)


def accept_hint(finding: str) -> str:
    """The exact command fragment that clears this finding, for a refusal to end with."""
    return (
        f"If you have read the fixtures and this is the source rather than the capture, "
        f"re-run with `--accept-partial {finding}`; the acceptance is recorded in "
        f"brief.json and travels with the draft."
    )


def _looks_like_a_fingerprint_block(exc: BaseException) -> bool:
    """True when this failure is a 403 that reads as TLS fingerprinting.

    Duck-typed rather than matched against ``httpx.HTTPStatusError`` so a test double
    (and any future transport) can raise the same shape. Anything without a 403
    response attached is somebody else's error and is re-raised untouched.
    """
    response = getattr(exc, "response", None)
    if response is None or getattr(response, "status_code", None) != 403:
        return False
    try:
        headers = {str(k).lower(): str(v).lower() for k, v in dict(response.headers).items()}
    except (AttributeError, TypeError, ValueError):
        headers = {}
    if any(name in headers for name in _BLOCK_HEADERS):
        return True
    if "cloudflare" in headers.get("server", ""):
        return True
    body = str(getattr(response, "text", "") or "").lower()
    return any(marker in body for marker in _BLOCK_MARKERS)


# --- the brief ---


def capture_info(outcome: CaptureOutcome, *, fetched_at: str | None = None) -> CaptureInfo:
    """The registry's view of this capture.

    ``listing_record_count`` is the records the listing walk discovered. For HTML
    that is also the size of the corpus, because the listing is walked exhaustively;
    for a feed it is what the walk held, which equals the corpus whenever
    ``records_total`` does. Nothing else in the pipeline produces this number.
    """
    result = outcome.result
    return CaptureInfo(
        session_id=outcome.session.session_id,
        shape=outcome.shape,
        listing_pages=len(result.listing_paths),
        records_captured=result.records_captured,
        records_total=result.records_total,
        pagination_kind=result.pagination_kind,
        pagination_detail=result.pagination_detail,
        transport=outcome.transport,
        fetched_at=fetched_at or outcome.session.started_at,
        listing_record_count=result.records_captured,
        truncated=result.truncated,
        record_list_identified=result.record_list_identified,
    )


def build_brief(
    candidate: Candidate,
    outcome: CaptureOutcome,
    *,
    now: str,
    adapter_name: str | None = None,
    accepted: Iterable[str] = (),
) -> dict[str, Any]:
    """Assemble ``brief.json`` from the candidate and what the capture produced.

    The field inventory here is the Scout's, unmeasured: ``coverage`` is None until
    the inventory pass runs and rewrites this file. No ``floors`` key is written for
    the same reason — an empty one reads as "no floors needed", which is a different
    statement from "nothing has been measured yet".

    That absence is not a strong enough signal on its own: a consumer written with
    ``brief.get("floors", {})`` reads it as "no floors needed" and renders a test
    module that asserts nothing. So the file says so in a key that has to be read —
    ``inventory_measured: false`` — and the inventory pass flips it when it rewrites
    the file. A brief is written for every capture that was not refused, including one
    whose findings an operator accepted; ``accepted_findings`` names those, so the
    acceptance travels with the artefact.
    """
    info = capture_info(outcome)
    from dataclasses import asdict

    from casesignal.drafter.runtime import source_spec

    result = outcome.result
    return {
        "runtime": source_spec(candidate, outcome.shape, outcome.transport),
        "fixture_manifest": [asdict(f) for f in outcome.session.fixtures],
        "adapter_name": adapter_name_for(candidate, override=adapter_name),
        "source_key": source_key_for(candidate, now[:10], override=adapter_name),
        "inventory_measured": False,
        "accepted_findings": sorted(accepted),
        "candidate_id": candidate.id,
        "captured_at": now,
        "state": candidate.state,
        "county": candidate.county,
        "level": candidate.level.value,
        "agency": candidate.agency,
        "agency_type": candidate.agency_type,
        "index_url": candidate.index_url,
        "channel": candidate.channel.value,
        "page_type": candidate.page_type,
        "shape": outcome.shape,
        "transport": outcome.transport,
        "session_id": info.session_id,
        "fixtures_root": outcome.session.fixtures_root,
        "listing_paths": list(result.listing_paths),
        "detail_paths": list(result.detail_paths),
        "dropped_urls": list(outcome.dropped_urls),
        "listing_pages": info.listing_pages,
        "records_captured": info.records_captured,
        "records_total": info.records_total,
        "listing_record_count": info.listing_record_count,
        "truncated": info.truncated,
        "record_list_identified": info.record_list_identified,
        "record_list_basis": result.record_list_basis,
        "pagination_kind": info.pagination_kind,
        "pagination_detail": info.pagination_detail,
        "detail_url_pattern": candidate.detail_url_pattern,
        "dataset_id": candidate.dataset_id,
        "source_id_strategy": candidate.source_id_strategy,
        "source_id_field": candidate.source_id_field,
        "robots": candidate.robots,
        "auth_required": candidate.auth_required,
        "needs_js": candidate.needs_js,
        "plottability": candidate.plottability,
        "plottability_basis": candidate.plottability_basis,
        "case_type_mix": list(candidate.case_type_mix),
        "gates": _gates_block(candidate),
        "case_count": _case_count_block(candidate),
        "fields": {name: _field_block(spec) for name, spec in candidate.fields.items()},
    }


def write_brief(draft_dir: Path, brief: dict[str, Any]) -> Path:
    """Write ``brief.json`` atomically, so an interrupted run never truncates it."""
    draft_dir.mkdir(parents=True, exist_ok=True)
    path = draft_dir / _BRIEF
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(brief, indent=2), encoding="utf-8")
    os.replace(tmp, path)  # atomic: the previous brief stands until this lands
    return path


def _gates_block(candidate: Candidate) -> dict[str, Any] | None:
    gates = candidate.gates
    if gates is None:
        return None
    return {
        "cold_homicide": gates.cold_homicide.value,
        "official_first_party": gates.official_first_party.value,
        "reason": gates.reason,
    }


def _case_count_block(candidate: Candidate) -> dict[str, Any] | None:
    count = candidate.case_count
    if count is None:
        return None
    return {
        "value": count.value,
        "confidence": count.confidence.value if count.confidence else None,
        "basis": count.basis,
    }


def _field_block(spec: Any) -> dict[str, Any]:
    return {
        "present": spec.present,
        "location": spec.location.value,
        "page": spec.page.value if spec.page else None,
        "example": spec.example,
        "encoding": spec.encoding,
        "coverage": spec.coverage,
        "locator": spec.locator,
        "locator_kind": spec.locator_kind.value if spec.locator_kind else None,
    }
