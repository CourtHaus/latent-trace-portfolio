"""The whole SP2 chain, end to end, with both agent passes faked and no network.

Fourteen modules were built and reviewed one at a time. Nothing had ever drafted a
source from a registry row to a green test run, and every defect this test found on
its first pass was a defect in the JOINS rather than in any module: the generated
tests looking for fixtures nobody copied, the drafting worktree importing the
adapter from the operator's checkout instead of its own, and the repository's
test-database guard failing every round before a single assertion ran.

What is real here: the capture walk, the fixture manifest, the inventory
measurement, the whole generator, git and its worktrees, and pytest -- the
generated modules are collected and run by a real subprocess, so a parser that
does not work cannot pass. What is faked: the HTTP client (a local corpus) and
the drafting agent (:class:`~casesignal.drafter.client.FakeDrafterClient` for BOTH
passes, scripted with the files a competent agent would have written).
"""

from __future__ import annotations

import ast
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from casesignal.drafter import capture as capture_mod
from casesignal.drafter import cli
from casesignal.drafter.client import FakeDrafterClient
from casesignal.scout.models import (
    Candidate,
    CaseCount,
    Channel,
    Confidence,
    FieldSpec,
    GateResult,
    Gates,
    Level,
    Location,
    Page,
    Status,
)
from casesignal.scout.registry import Registry

REAL_ROOT = Path(__file__).resolve().parents[2]
INDEX_URL = "https://example.invalid/cold-cases"
CANDIDATE_ID = "example.invalid/cold-cases"

# --- the source ---
#
# Four records on one page, so the walk is a census and the generator renders an
# exact-count assertion. Record #1 carries no NARRATIVE line: that is what makes
# the narrative floor 0.65 rather than 0.9, and it is the one thing in the corpus
# that keeps a measured floor from being indistinguishable from a declared one.

_RECORDS = (
    ("ALICE ANDERSON", "ZZ-0001", "Tulsa", "1998-04-02", "Found on a county road."),
    ("BRIAN BOOTH", "ZZ-0002", "Creek", "2001-11-19", None),
    ("CARLA CRUZ", "ZZ-0003", "Tulsa", "2004-06-30", "Last seen leaving work."),
    ("DEREK DIAZ", "ZZ-0004", "Osage", "2011-01-08", "Recovered from the river."),
)


def _listing_html() -> bytes:
    blocks = []
    for name, number, county, date, narrative in _RECORDS:
        lines = [
            f'<li class="case" data-case-id="{number}">',
            f"<h3>NAME: {name}</h3>",
            f"<p>CASE NUMBER: {number}</p>",
            f"<p>COUNTY: {county}</p>",
            f"<p>DATE: {date}</p>",
        ]
        if narrative is not None:
            lines.append(f"<p>NARRATIVE: {narrative}</p>")
        lines.append("</li>")
        blocks.append("\n".join(lines))
    body = "\n".join(blocks)
    return f"<html><body><ul>\n{body}\n</ul></body></html>\n".encode()


class _Response:
    def __init__(self, body: bytes) -> None:
        self.content = body
        self.status_code = 200

    @property
    def text(self) -> str:
        return self.content.decode("utf-8")


class _FakeHttpClient:
    """One host, one page, and a refusal for anything else the capture reaches for."""

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.requested: list[str] = []

    def get(self, url: str) -> _Response:
        self.requested.append(url)
        if url != INDEX_URL:
            raise AssertionError(f"the capture asked for {url}, which is not the corpus")
        return _Response(_listing_html())

    def close(self) -> None:
        return None


# --- the candidate ---


def _field(location: Location) -> FieldSpec:
    return FieldSpec(present=True, location=location, page=Page.LIST)


def _candidate() -> Candidate:
    return Candidate(
        id=CANDIDATE_ID,
        level=Level.STATE,
        state="ZZ",
        index_url=INDEX_URL,
        channel=Channel.WEB,
        agency="Example Cold Case Unit",
        agency_type="state_investigative",
        page_type="html listing",
        needs_js=False,
        robots="allowed",
        auth_required=False,
        gates=Gates(
            cold_homicide=GateResult.PASS,
            official_first_party=GateResult.PASS,
            reason="state investigative bureau publishing its own unsolved homicides",
        ),
        case_count=CaseCount(value=4, confidence=Confidence.EXACT, basis="listing count"),
        plottability=1.0,
        plottability_basis="every record carries a county",
        case_type_mix=["homicide"],
        source_id_strategy="source_field",
        source_id_field="case_number",
        fields={
            "victim_name": _field(Location.STRUCTURED),
            "case_number": _field(Location.STRUCTURED),
            "county": _field(Location.STRUCTURED),
            "incident_date": _field(Location.STRUCTURED),
            "narrative": _field(Location.NARRATIVE),
        },
        status=Status.ACCEPTED,
    )


# --- the two agent passes ---

_LOCATORS = {
    "victim_name": {"kind": "label", "value": "NAME:", "page": "list"},
    "case_number": {"kind": "label", "value": "CASE NUMBER:", "page": "list"},
    "county": {"kind": "label", "value": "COUNTY:", "page": "list"},
    "incident_date": {"kind": "label", "value": "DATE:", "page": "list"},
    "narrative": {"kind": "label", "value": "NARRATIVE:", "page": "list"},
}


def _expectation(index: int) -> dict[str, Any]:
    name, number, county, date, narrative = _RECORDS[index]
    values = {
        "victim_name": name,
        "case_number": number,
        "county": county,
        "incident_date": date,
    }
    if narrative is not None:
        values["narrative"] = narrative
    return {"record_key": f"listing_1.html#{index}", "values": values}


def _reader_round(cwd: Path) -> None:
    """What the reader pass writes: two JSON files and nothing else."""
    (cwd / "locators.json").write_text(json.dumps(_LOCATORS, indent=2), encoding="utf-8")
    # First, last, and the most degenerate record -- the three the prompt asks for.
    (cwd / "expectations.json").write_text(
        json.dumps([_expectation(0), _expectation(3), _expectation(1)], indent=2),
        encoding="utf-8",
    )


_SCRAPE = '''"""Listing parse for the drafted adapter, written by the parser pass."""

from __future__ import annotations

from typing import Any

from bs4 import BeautifulSoup

_LABELS = {
    "NAME": "case_name",
    "CASE NUMBER": "source_case_id",
    "COUNTY": "county",
    "DATE": "incident_date",
    "NARRATIVE": "narrative",
}


def parse_listing(html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    records: list[dict[str, Any]] = []
    for node in soup.select("li.case"):
        found: dict[str, Any] = {name: None for name in _LABELS.values()}
        for line in node.get_text("\\n").splitlines():
            label, sep, rest = line.partition(":")
            if not sep:
                continue
            field = _LABELS.get(label.strip())
            if field is not None and rest.strip():
                found[field] = rest.strip()
        records.append(found)
    return records
'''

_TRANSFORM = '''"""Transform for the drafted adapter, written by the parser pass."""

from __future__ import annotations

from typing import Any


def to_case(record: dict[str, Any]) -> dict[str, Any]:
    return dict(record, case_type="homicide")


def transform(context: Any) -> None:
    for raw in context.get_metadata("raw_records") or []:
        context.get_metadata("case_sink")(to_case(raw))
'''


def _parsers(adapter_name: str) -> str:
    return f'''def parse_records(html: str, *, base_url: str) -> list[dict[str, Any]]:
    """One dict per case block on a listing page, in document order."""
    from casesignal.etl.adapters.{adapter_name}.scrape import parse_listing

    logger.debug("parsing a listing from %s", base_url)
    return parse_listing(html)


def parse_detail(html: str, *, url: str) -> dict[str, Any]:
    """This source publishes no detail pages; every field is on the listing."""
    return {{}}


'''


def _parser_round(adapter_name: str) -> Any:
    def write(cwd: Path) -> None:
        package = cwd / "src" / "casesignal" / "etl" / "adapters" / adapter_name
        adapter = package / "adapter.py"
        text = adapter.read_text(encoding="utf-8")
        start = text.index("def parse_records(")
        end = text.index("def entry_from_record(")
        adapter.write_text(text[:start] + _parsers(adapter_name) + text[end:], encoding="utf-8")
        (package / "scrape.py").write_text(_SCRAPE, encoding="utf-8")
        (package / "transform.py").write_text(_TRANSFORM, encoding="utf-8")

    return write


# --- the repository the draft lands in ---


def _git(repo: Path, *args: str) -> None:
    proc = subprocess.run(
        ["git", "-c", "user.name=T", "-c", "user.email=t@localhost", *args],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"git {' '.join(args)}: {proc.stderr}"


def _build_repo(tmp_path: Path) -> Path:
    """A real checkout: this repository's own src tree, its pytest config, its conftest.

    The conftest matters most. The repository's ``tests/conftest.py`` redirects
    ``DATABASE_URL`` and then refuses the session unless that database is reachable
    and sentinel-stamped, which would fail every drafting round with a pytest usage
    error. Copying it in is how this test proves the CLI's replacement of it inside
    the throwaway worktree actually happens.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    shutil.copytree(
        REAL_ROOT / "src",
        repo / "src",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    shutil.copy2(REAL_ROOT / "pyproject.toml", repo / "pyproject.toml")
    shutil.copytree(
        REAL_ROOT / "tests" / "support",
        repo / "tests" / "support",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    shutil.copy2(REAL_ROOT / "tests" / "conftest.py", repo / "tests" / "conftest.py")
    for rel in (
        "tests/__init__.py",
        "tests/unit/etl/__init__.py",
        "tests/unit/etl/adapters/__init__.py",
    ):
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("", encoding="utf-8")
    (repo / ".gitignore").write_text("data/\n.worktrees/\n__pycache__/\n", encoding="utf-8")

    _git(repo, "init", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "the checkout this draft lands in")
    return repo


# --- the run ---


@pytest.fixture
def drafted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    repo = _build_repo(tmp_path)
    candidate = _candidate()
    adapter_name = capture_mod.adapter_name_for(candidate)

    registry = Registry({}, [])
    registry.upsert(candidate)
    registry.save(repo / "data" / "scout" / "registry.yaml")

    http = _FakeHttpClient()
    agent = FakeDrafterClient(scripted=[_reader_round, _parser_round(adapter_name)])

    def factory(**kwargs: Any) -> _FakeHttpClient:
        http.kwargs = kwargs
        return http

    monkeypatch.setattr(cli, "_http_client_factory", lambda: factory)
    monkeypatch.setattr(cli, "_drafter_client", lambda: agent)
    monkeypatch.chdir(repo)

    code = cli.main(["run", CANDIDATE_ID, "--branch", "draft/e2e"])
    return {
        "repo": repo,
        "adapter": adapter_name,
        "code": code,
        "agent": agent,
        "http": http,
        "draft_dir": repo / "data" / "drafts" / adapter_name,
        "worktree": repo / ".worktrees" / adapter_name,
    }


def test_the_chain_produces_a_complete_draft_tree(drafted: dict[str, Any]) -> None:
    """claim -> capture -> read -> measure -> scaffold -> draft -> verify, green."""
    repo: Path = drafted["repo"]
    adapter: str = drafted["adapter"]
    draft_dir: Path = drafted["draft_dir"]

    assert drafted["code"] == 0
    assert adapter == "cold_case_zz_eccu"

    # The capture: fixtures on disk, and a manifest that locates them.
    assert (draft_dir / "fixtures" / "listing_1.html").is_file()
    manifest = json.loads((draft_dir / "manifest.json").read_text(encoding="utf-8"))
    assert [record["path"] for record in manifest["fixtures"]] == ["listing_1.html"]

    # The reader pass, and then the pass that nothing else in the repository calls.
    assert (draft_dir / "locators.json").is_file()
    assert (draft_dir / "expectations.json").is_file()
    brief = json.loads((draft_dir / "brief.json").read_text(encoding="utf-8"))
    assert brief["inventory_measured"] is True
    assert brief["records_captured"] == 4 and brief["records_total"] == 4

    # The measurement is a measurement: a structured field at its fixed floor, and a
    # narrative field whose floor came off the corpus rather than out of a constant.
    assert brief["floors"]["case_name"] == 0.95
    assert brief["floors"]["narrative"] == pytest.approx(0.65)
    assert brief["coverage"]["narrative"]["matched"] == 3
    assert brief["vacuous_floors"] == [] and brief["unreachable_floors"] == []

    # The generator's whole output, in the operator's checkout, and every module of
    # it importable Python.
    generated = [
        f"src/casesignal/etl/adapters/{adapter}/__init__.py",
        f"src/casesignal/etl/adapters/{adapter}/adapter.py",
        f"src/casesignal/etl/adapters/{adapter}/register.py",
        f"src/casesignal/etl/adapters/{adapter}/raw_load.py",
        f"tests/unit/etl/adapters/test_{adapter}_invariants.py",
        f"tests/unit/etl/adapters/test_{adapter}_expectations.py",
        f"docs/drafts/{adapter}.md",
        "src/casesignal/etl/sources/cold_case_zz.yaml",
    ]
    for rel in generated:
        assert (repo / rel).is_file(), rel
        if rel.endswith(".py"):
            ast.parse((repo / rel).read_text(encoding="utf-8"), filename=rel)
    assert f"{adapter}" in (repo / "src/casesignal/etl/runners/run_pipeline.py").read_text()
    # Both generated modules read tests/fixtures/<adapter>; the memo says to copy
    # them by hand, which is a step no first round would ever have taken.
    assert (repo / "tests" / "fixtures" / adapter / "listing_1.html").is_file()

    # The loop: one round, green, with its transcript kept.
    report = json.loads((draft_dir / "loop.json").read_text(encoding="utf-8"))
    assert report["passed"] is True
    assert report["stopped_because"] == "green"
    assert (draft_dir / "rounds" / "00" / "prompt.md").is_file()


def test_verify_resolves_to_pass_over_the_drafted_parser(drafted: dict[str, Any]) -> None:
    """A second, independent verification of the tree the run left behind."""
    args = cli.build_parser().parse_args(["verify", drafted["adapter"]])
    report = cli._verify(args, drafted["repo"], Path("data/drafts"), drafted["adapter"])
    assert report.status.value == "PASS"
    assert report.invariants.passed and report.invariants.ran
    assert report.expectations.passed and report.expectations.ran
    assert report.todos == []
    assert report.coverage["narrative"] == pytest.approx(0.75)


def test_the_golden_module_never_entered_the_worktree(drafted: dict[str, Any]) -> None:
    """The barrier, checked on the tree rather than on the call.

    The scaffold writes the golden module into the operator's checkout; staging it
    into the worktree alongside everything else would let the parser pass read the
    values it is graded against and satisfy every golden test by hardcoding.
    """
    worktree: Path = drafted["worktree"]
    adapter: str = drafted["adapter"]
    assert (worktree / f"tests/unit/etl/adapters/test_{adapter}_invariants.py").is_file()
    assert not (worktree / f"tests/unit/etl/adapters/test_{adapter}_expectations.py").exists()
    assert list(worktree.rglob("test_*expectations.py")) == []
    # And it is not in the round's prompt either, which is the other way in.
    prompts = "\n".join(drafted["agent"].prompts)
    for _name, _number, _county, _date, narrative in _RECORDS:
        if narrative:
            assert narrative not in prompts
    assert "ALICE ANDERSON" not in prompts


def test_the_worktree_runs_without_the_repository_test_database_guard(
    drafted: dict[str, Any],
) -> None:
    """Every round would exit 4 on a machine with Postgres down, after being bought."""
    conftest = (drafted["worktree"] / "tests" / "conftest.py").read_text(encoding="utf-8")
    assert "db_guard" not in conftest
    assert "enforce_test_database" not in conftest
    assert "sys.path.insert" in conftest


def test_the_draft_lands_on_the_branch_the_operator_named(drafted: dict[str, Any]) -> None:
    proc = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=drafted["repo"],
        capture_output=True,
        text=True,
    )
    assert proc.stdout.strip() == "draft/e2e"


def test_the_agent_ran_under_a_budget_and_a_restricted_tool_set(
    drafted: dict[str, Any],
) -> None:
    calls = drafted["agent"].calls
    assert len(calls) == 2, "one reader round and one parser round"
    for call in calls:
        assert call["max_budget_usd"] is not None
        assert "Bash" not in call["allowed_tools"]
    assert set(calls[0]["allowed_tools"]) <= {"Read", "Grep", "Write"}


def test_nothing_reached_the_network_but_the_index_url(drafted: dict[str, Any]) -> None:
    assert drafted["http"].requested == [INDEX_URL]
    assert drafted["http"].kwargs["allowed_hosts"] == frozenset({"example.invalid"})
    assert drafted["http"].kwargs["bypass_robots_hosts"] == frozenset()
