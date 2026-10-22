"""Turn harness web-search results into deduped candidate rows."""

from __future__ import annotations

from typing import Any

from casesignal.scout.models import Candidate, Channel, Level, dedup_key


def candidates_from_results(results: list[dict[str, Any]], seen: set[str]) -> list[Candidate]:
    out: list[Candidate] = []
    for r in results:
        url = r["url"]
        cid = dedup_key(Channel.WEB, None, url)
        if cid in seen:
            continue
        seen.add(cid)
        out.append(
            Candidate(
                id=cid,
                level=Level(r["level"]),
                state=r["state"],
                index_url=url,
                channel=Channel.WEB,
                county=r.get("county"),
            )
        )
    return out
