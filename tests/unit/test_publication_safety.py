"""Regression checks for publication tooling without accessing a real database."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from scripts import check_repository_docs as docs

ROOT = Path(__file__).resolve().parents[2]


def test_docs_ignore_example_links_but_check_real_links() -> None:
    content = (
        '# Guide\n[guide](guide.md)\n`<a href="/example">`\n```html\n<a href="/example">\n```\n'
    )
    assert docs.local_links(content) == [(2, "guide.md")]


def test_docs_reject_links_to_untracked_local_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(docs, "ROOT", tmp_path)
    (tmp_path / "README.md").write_text("[private](private.md)\n")
    (tmp_path / "private.md").write_text("Private local material\n")
    assert any("missing tracked link target" in e for e in docs.check_files({"README.md"}))


def test_repository_hygiene_rejects_private_artifacts() -> None:
    errors = docs.check_files({"data/raw/export.csv", "backup.sql.gz", ".env.production"})
    assert len(errors) == 3
    assert all("must not be tracked" in e for e in errors)


@pytest.mark.parametrize(
    "host,database", [("example.test", "casesignal_restore_test"), ("localhost", "casesignal")]
)
def test_restore_rejects_unsafe_destinations(tmp_path: Path, host: str, database: str) -> None:
    backup = tmp_path / "backup.dump"
    backup.write_bytes(b"fixture")
    env = {**os.environ, "PGHOST": host, "PGDATABASE": database, "PATH": "/usr/bin:/bin"}
    result = subprocess.run(
        ["bash", str(ROOT / "tools/restore_local_seed.sh"), str(backup)],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "local database host" in result.stderr or "fresh name" in result.stderr


def test_restore_does_not_replace_existing_database(tmp_path: Path) -> None:
    backup = tmp_path / "backup.dump"
    backup.write_bytes(b"fixture")
    log = tmp_path / "calls"
    for name, body in {
        "pg_restore": 'echo "$*" >> "$CALL_LOG"\nexit 0\n',
        "createdb": "exit 1\n",
    }.items():
        script = tmp_path / name
        script.write_text("#!/bin/sh\n" + body)
        script.chmod(0o700)
    env = {
        **os.environ,
        "PGHOST": "localhost",
        "PGDATABASE": "casesignal_restore_test",
        "PATH": f"{tmp_path}:/usr/bin:/bin",
        "CALL_LOG": str(log),
    }
    result = subprocess.run(
        ["bash", str(ROOT / "tools/restore_local_seed.sh"), str(backup)],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert log.read_text().splitlines() == [f"--list {backup}"]


def test_backup_requires_explicit_destination(tmp_path: Path) -> None:
    env = {
        **os.environ,
        "DATABASE_URL": "postgresql://localhost/unused",
        "BACKUP_BUCKET": "",
        "BACKUP_WORKDIR": str(tmp_path),
    }
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/backup_corpus.sh")], env=env, capture_output=True, text=True
    )
    assert result.returncode != 0
    assert "set BACKUP_BUCKET" in result.stderr
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("name", [
    "tests/fixtures/new_capture.html", "docs/audits/case-report.md",
    "data/validation/labels.yaml", "archive.zip", "agency.pdf",
])
def test_snapshot_rejects_unreviewed_data(name: str, tmp_path: Path,
                                         monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(docs, "ROOT", tmp_path)
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Invented content\n")
    assert any("must not be tracked" in error for error in docs.check_files({name}))
