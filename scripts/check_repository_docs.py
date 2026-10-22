"""Check local Markdown links, documentation inventory, and private artifact boundaries.

Uses only the standard library. It does not check remote URLs or heading anchors.
Run from any directory; --write-inventory refreshes the documentation catalog.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = "docs/documentation-inventory.md"
RECORD_PREFIXES = (
    "docs/superpowers/",
    "docs/audits/",
    "docs/evidence/",
    "docs/design/",
    "docs/notes/",
)
CURRENT_RECORDS: set[str] = set()


def repository_files() -> set[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return {name for name in result.stdout.split("\0") if name and (ROOT / name).is_file()}


def is_record(name: str) -> bool:
    return name.startswith(RECORD_PREFIXES) and name not in CURRENT_RECORDS


def local_links(content: str) -> list[tuple[int, str]]:
    """Extract ordinary inline/reference links and HTML asset paths outside fences."""
    links = []
    fence = ""
    for number, line in enumerate(content.splitlines(), 1):
        stripped = line.lstrip()
        match = re.match(r"(`{3,}|~{3,})", stripped)
        if match:
            token = match.group(1)
            if not fence:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = ""
            continue
        if fence:
            continue
        line = re.sub(r"`[^`]*`", "", line)
        targets = re.findall(r"\]\((<[^>]+>|[^\s)]+)(?:\s+\"[^\"]*\")?\)", line)
        reference = re.match(r"\s*\[[^\]]+\]:\s*(<[^>]+>|\S+)", line)
        if reference:
            targets.append(reference.group(1))
        targets.extend(re.findall(r'(?:src|href)="([^"]+)"', line))
        for target in targets:
            target = target.strip("<>")
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            links.append((number, unquote(parsed.path)))
    return links


def inventory_content(files: set[str]) -> str:
    lines = [
        "# Documentation inventory",
        "",
        "Generated with `python3 scripts/check_repository_docs.py --write-inventory`.",
        "Every tracked Markdown document is classified below. Current guides describe",
        "supported workflows; dated records preserve their original context and may",
        "contain superseded code, paths, or proposals. Classification is not a claim",
        "that every historical code example has been rerun.",
        "",
        "| Document | Role |",
        "| --- | --- |",
    ]
    for name in sorted(n for n in files if n.endswith(".md") and n != INVENTORY):
        target = os.path.relpath(name, "docs").replace(os.sep, "/")
        role = (
            "Dated design / evidence record"
            if is_record(name)
            else "Current guide / project policy"
        )
        lines.append(f"| [{name}]({target}) | {role} |")
    return "\n".join(lines) + "\n"


def check_files(files: set[str]) -> list[str]:
    errors = []
    for name in sorted(files):
        path = Path(name)
        if (
            path.name.startswith(".env")
            and name not in {".env.example", "frontend/.env.local.example"}
            or name.endswith((".dump", ".sql.gz", ".sql.bz2", ".sql.xz", ".pem", ".key"))
            or name.startswith(
                ("data/raw/", "data/photos/", "data/drafts/", "data/scout/", "publication-audit/")
            )
            or name.startswith("docs/notes/phase-6-wyoming-source-exports/")
            or name.startswith(("docs/audits/", "docs/evidence/", "docs/notes/",
                                "docs/superpowers/", "data/validation/"))
            or (name.startswith("tests/fixtures/") and name not in {
                "tests/fixtures/README.md",
                "tests/fixtures/scout/arcgis_hub.json",
                "tests/fixtures/scout/socrata_catalog.json",
                "tests/fixtures/scout/websearch_results.jsonl",
                "tests/fixtures/scout/verdicts/tx_dps_rangers.json",
            })
            or name.endswith((".pdf", ".zip", ".tar", ".tgz", ".gz"))
        ):
            errors.append(f"{name}: private/runtime artifact must not be tracked")
        if not name.endswith(".md"):
            continue
        content = (ROOT / name).read_text(encoding="utf-8")
        if is_record(name) and "Documentation status: dated record" not in content:
            errors.append(f"{name}: missing historical-context notice")
        for line, target in local_links(content):
            resolved = (ROOT / path.parent / target).resolve()
            if not resolved.is_relative_to(ROOT):
                errors.append(f"{name}:{line}: link leaves the repository: {target}")
                continue
            rel = resolved.relative_to(ROOT).as_posix()
            available = rel in files or any(f.startswith(rel.rstrip("/") + "/") for f in files)
            if not available:
                errors.append(f"{name}:{line}: missing tracked link target: {target}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-inventory", action="store_true")
    args = parser.parse_args()
    files = repository_files()
    expected = inventory_content(files)
    if args.write_inventory:
        (ROOT / INVENTORY).write_text(expected)
        files.add(INVENTORY)
    errors = check_files(files)
    if not (ROOT / INVENTORY).exists() or (ROOT / INVENTORY).read_text() != expected:
        errors.append(f"{INVENTORY}: stale; run with --write-inventory")
    for error in errors:
        print(error)
    print(f"Checked {sum(n.endswith('.md') for n in files)} Markdown files; {len(errors)} problems")
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
