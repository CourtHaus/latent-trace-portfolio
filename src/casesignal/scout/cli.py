"""CLI: casesignal-source-scout.

Subcommands:
  discover  --tier state | --state XX --counties : build the frontier work queue,
            run discovery, capture proof evidence, emit a classification worklist.
  finalize                                        : ingest classification verdicts,
            estimate + score, update the registry, render the dossier.
  recheck   rejected                              : re-queue prior rejects for reclassification.
"""

from __future__ import annotations

import argparse

from casesignal.scout.models import Status
from casesignal.scout.registry import Registry


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="casesignal-source-scout")
    sub = parser.add_subparsers(dest="command", required=True)

    discover = sub.add_parser("discover", help="build frontier + run discovery")
    scope = discover.add_mutually_exclusive_group(required=True)
    scope.add_argument("--tier", choices=["state"])
    scope.add_argument("--state", metavar="XX")
    discover.add_argument("--counties", action="store_true")
    discover.add_argument("--max-candidates", type=int, default=50)

    sub.add_parser("finalize", help="ingest verdicts, score, render dossier")

    recheck = sub.add_parser("recheck", help="re-queue prior verdicts for reclassification")
    recheck.add_argument("target", choices=["rejected"])
    return parser


def main(argv: list[str] | None = None) -> int:
    from pathlib import Path

    from casesignal.scout import run

    args = build_parser().parse_args(argv)
    data_dir = Path("data/scout")
    sources_dir = Path("src/casesignal/etl/sources")
    registry_path = data_dir / "registry.yaml"

    if args.command == "discover":
        from casesignal.etl.services.polite_http import PoliteHTTPClient

        scope = run.Scope(
            tier=getattr(args, "tier", None),
            state=getattr(args, "state", None),
            counties=args.counties,
            max_candidates=args.max_candidates,
        )
        # The web-search seam is filled by Claude Code at run time; the plain CLI
        # invocation uses an empty search (search_fn=lambda _q: []) so it never
        # silently fabricates results. The catalog channel, however, is deterministic
        # core Python, so the CLI drives it directly. The allowlist REPLACES the
        # default so this client can only reach the two catalog hosts.
        with PoliteHTTPClient(
            allowed_hosts={"api.us.socrata.com", "hub.arcgis.com"}
        ) as catalog_client:
            worklist = run.discover(
                scope,
                registry_path,
                sources_dir,
                data_dir,
                search_fn=lambda _q: [],
                catalog_client=catalog_client,
            )
        print(f"worklist: {worklist}")
        return 0

    if args.command == "finalize":
        from datetime import date

        dossier = run.finalize(
            registry_path, data_dir / "verdicts", date.today().isoformat(), data_dir
        )
        print(f"dossier: {dossier}")
        return 0

    if args.command == "recheck":
        reg = Registry.load(registry_path)
        for c in reg.by_status(Status.REJECTED):
            c.status = Status.CANDIDATE
            reg.upsert(c)
        reg.save(registry_path)
        print("recheck: rejected candidates re-queued")
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
