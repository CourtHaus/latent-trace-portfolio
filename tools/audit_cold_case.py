"""Read-only data-quality audit for cold-case ingestions.

Run as a module from the repo root (tools.audit is a namespace package):

  APP_ENV=dev DATABASE_URL=postgresql+psycopg2://casesignal:casesignal@localhost:5433/casesignal \
    python -m tools.audit_cold_case --source cold_case_fl_fdle

The application package lives under ``src/``; ``_ensure_src_on_path`` adds it so
the command works from a fresh checkout even when ``casesignal`` is not
installed (mirrors tests/conftest.py). Application imports happen inside
``main`` so the bootstrap runs first.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _ensure_src_on_path() -> None:
    """Add the repo's ``src/`` to sys.path so ``casesignal`` imports without an
    editable install. No-op if it's already importable."""
    src = Path(__file__).resolve().parent.parent / "src"
    if src.is_dir() and str(src) not in sys.path:
        sys.path.insert(0, str(src))


def main(argv: list[str] | None = None) -> int:
    _ensure_src_on_path()

    from casesignal.etl.config import settings
    from casesignal.etl.services.db import create_db_engine, create_session_factory
    from tools.audit.model import Finding
    from tools.audit.render import render_text
    from tools.audit.resolve import resolve_context
    from tools.audit.rules_fl import SOURCE_RULES

    parser = argparse.ArgumentParser(description="Audit a cold-case ingestion.")
    parser.add_argument("--source", required=True, choices=sorted(SOURCE_RULES))
    parser.add_argument("--format", choices=("text", "md"), default="text")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    config = SOURCE_RULES[args.source]
    engine = create_db_engine(settings.database_url)
    sf = create_session_factory(engine)

    with sf() as session:
        ctx = resolve_context(
            session, source=config.source,
            source_code=config.source_code, state=config.state,
        )
        if ctx is None:
            print(f"No published dataset_version for {config.source_code}", file=sys.stderr)
            return 2
        results = []
        for rule in config.rules:
            try:
                with session.begin_nested():
                    finding = rule.run(session, ctx)
            except Exception as exc:  # a broken rule must not abort the whole audit
                # count=1 so the error is VISIBLE (has_findings is count>0); also warn.
                # begin_nested() rolls back to the savepoint on exception, keeping the
                # outer transaction alive so subsequent rules can still execute.
                print(f"RULE ERROR [{rule.id}]: {exc!r}", file=sys.stderr)
                finding = Finding(1, [], f"RULE ERROR: {exc!r}")
            results.append((rule, finding))

    report = render_text(ctx, results, verbose=args.verbose)
    if args.out or args.format == "md":
        out = args.out or Path(f"publication-audit/fl-fdle-audit-dv{ctx.dataset_version_id}.md")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report + "\n", encoding="utf-8")
        print(f"Wrote {out}")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
