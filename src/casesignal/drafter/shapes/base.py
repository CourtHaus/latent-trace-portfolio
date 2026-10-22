"""What a capture hands downstream, whatever transport it came off.

An HTML listing and a Socrata feed share nothing at the transport layer and
everything after it: both end as a pile of per-record payloads that the
inventory pass measures field coverage across. These types are that common
ground, so nothing downstream has to branch on where a record came from.

The HTTP types here are structural on purpose. The real client is
``casesignal.etl.services.polite_http.PoliteHTTPClient`` — rate limiting, robots,
host allowlist, redirect revalidation — but a capture only ever calls ``get``,
and a test double that also only implements ``get`` should type-check without
importing httpx. Both members are read-only properties so ``httpx.Response``,
whose ``text`` and ``content`` are properties, satisfies the protocol.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from casesignal.drafter.session import CaptureSession
from casesignal.scout.models import Candidate

# Why a capture believes the objects it measured are the source's records. It is the
# *reason* behind ``record_list_identified``, and the two are not interchangeable: a
# consumer deciding whether to withhold a census only needs the boolean, while one
# deciding whether a human has to look needs to know which way it went false.
#
# ``named``      the source named the list, or there was nothing to choose between
#                (a feed, an HTML selector match, a document that is itself an array).
# ``bounded``    the document search hit a width or depth bound before it finished, so
#                a rival candidate may sit in the part it never read. What it did find
#                was still named by the source; what it cannot claim is that the name
#                was unique.
# ``ambiguous``  the document named more than one plausible record list.
# ``guessed``    no list under any known record key; the rows are the shallowest list
#                of objects in the document, which is a guess and nothing more.
# ``wrapped``    the objects measured are wrappers around the records, not the records:
#                an HTML listing whose whole list sits inside one generic container, or
#                a JSON list whose element holds a longer list a level below. The rows
#                are real markup and real objects, so this is not an empty capture -- it
#                is a capture that would count groups. Distinct from ``ambiguous``
#                because nothing here is a rival candidate: there is one list and it is
#                the wrong height.
# ``unreadable`` no record list was found at all, by name or by guess. Whether the
#                search finished or ran out of budget, nothing can point at the rows,
#                so both fold together here: the operator's next move is the same.
RECORD_LIST_NAMED = "named"
RECORD_LIST_BOUNDED = "bounded"
RECORD_LIST_AMBIGUOUS = "ambiguous"
RECORD_LIST_GUESSED = "guessed"
RECORD_LIST_WRAPPED = "wrapped"
RECORD_LIST_UNREADABLE = "unreadable"


class Response(Protocol):
    """The three things a capture reads off a response."""

    @property
    def status_code(self) -> int: ...

    @property
    def text(self) -> str: ...

    @property
    def content(self) -> bytes: ...


class HttpClient(Protocol):
    """A polite GET, and nothing else a capture is allowed to reach for."""

    def get(self, url: str) -> Response: ...


@dataclass(frozen=True)
class CapturedRecord:
    """One case as the source presented it, ready to be measured.

    ``key`` identifies the record within the capture (fixture name plus position),
    so a coverage report can point an operator at the exact page a field was
    missing from. ``payload`` is the markup or JSON for that one record, and
    ``page`` says which of the two surfaces it was taken from — ``"list"`` or
    ``"detail"``. A capture may hold both: records inside the detail sample carry
    their detail page, records outside it keep their listing block.

    ``detail_url`` is where this record's detail page lives, when the source has
    one. It is resolved during the listing walk, while the record's own markup and
    the URL of the page it came from are both still in hand; by the time the
    sampler runs, neither is.
    """

    key: str
    payload: str
    page: str
    detail_url: str | None = None


@dataclass(frozen=True)
class CaptureResult:
    """Everything one capture run produced, for the inventory and the brief.

    ``records_total`` is the size of the corpus the records were drawn from, and
    ``records_captured`` the number actually held. Equal means census, and only a
    census lets a later pass assert an exact record count against the fixtures;
    ``None`` means the size of the corpus is not known. Paths are relative to the
    capture's fixtures root, matching the session manifest.

    ``truncated`` says the capture stopped somewhere the source was still offering
    more. It is not the same statement as ``records_total is None``: a truncated
    walk always reports an unknown total, but a total can be unknown for reasons
    that are nobody's fault, and a refusal policy needs to tell those apart.

    ``record_list_identified`` says the records measured here are the ones the
    source designates as its records. A feed settles that by construction — SODA
    serves an array of rows, an ArcGIS layer serves ``features`` — so it is True for
    both, and for an HTML listing whose records are whatever the selector matched.
    It is False only where the question is open: a JSON payload embedded in a page
    is an arbitrary document, and ``data``, ``items``, ``results`` and ``value`` name
    a filter dropdown about as often as a case list, so a capture that had to choose
    between candidates says so rather than leaving a consumer to infer it. Without
    this the two are indistinguishable: "we never worked out which list held the
    records" and "we found the right list and it held some junk" both surface as an
    unknown total on a truncated walk, and the first is an operator's problem while
    the second is a parser's.

    It is the home of one more distinction that has nowhere else to live. A source
    that serves an empty record list and a document nobody could read both come back
    with no records and no total, and they are not the same thing: the first named
    where its records live and has none, and is a real answer about a real source;
    the second never said where to look, and is a capture waiting for someone to
    look at it. True and False respectively.
    """

    listing_paths: list[str] = field(default_factory=list)
    detail_paths: list[str] = field(default_factory=list)
    records: list[CapturedRecord] = field(default_factory=list)
    records_captured: int = 0
    records_total: int | None = None
    pagination_kind: str = "single"
    pagination_detail: str | None = None
    truncated: bool = False
    # Appended last with a default, the way ``truncated`` was in Task 5, so every
    # existing construction of this result keeps binding.
    record_list_identified: bool = True
    # And why. ``record_list_identified`` collapses four outcomes onto one boolean,
    # and two of them are not the same problem: a search that ran out of budget held
    # rows the source itself named, while a search that found two candidates or none
    # held rows that may belong to a nav menu. A consumer that refuses a capture on
    # the boolean alone refuses the first case for the second case's reason. See the
    # RECORD_LIST_* constants above.
    record_list_basis: str = RECORD_LIST_NAMED


class ShapeCapture(Protocol):
    """The call every shape capture answers to.

    Shape-specific tuning (an HTML detail sample, a JSON page size) is passed as
    keyword-only arguments with defaults, so each shape stays callable through
    this protocol without the caller knowing which shape it holds.
    """

    def __call__(
        self,
        candidate: Candidate,
        client: HttpClient,
        session: CaptureSession,
        draft_dir: Path,
        out_dir: Path,
    ) -> CaptureResult: ...
