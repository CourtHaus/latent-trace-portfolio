# Source Scout run-book

Use a private operator checkout for captures, registries, and agent responses.
Only reviewed synthetic examples belong in this portfolio snapshot.

Source Scout (SP1) finds and vets candidate cold-case data sources for new
states. It runs as a three-phase loop: discover, classify, finalize. Two of the
phases (web search in discover, and per-candidate classification) are filled by
Claude Code at run time, because they need harness tools (WebSearch and the
Agent subagent) that a plain CLI process cannot call. The bare CLI still runs
end to end on its own; it just does the catalog-only, deterministic part and
leaves the harness-driven seams empty so it never fabricates results.

All runtime state lives under `data/scout/` (git-ignored):

- `data/scout/registry.yaml` - the candidate registry (source of truth across runs).
- `data/scout/worklist.jsonl` - the classification work queue emitted by discover.
- `data/scout/evidence/<slug>/` - captured proof per candidate (listing + detail page).
- `data/scout/verdicts/<verdict_filename>` - one classification verdict JSON per candidate.
- `data/scout/dossier-<date>.md` - the human review artifact rendered by finalize.

The CLI entry point is `casesignal-source-scout`.

## 1. Discover

```
casesignal-source-scout discover --tier state
```

- Builds the state frontier (states not yet covered), runs the catalog channel
  (Socrata / ArcGIS), and writes `data/scout/worklist.jsonl` plus registry rows.
- The worklist is JSON Lines; each row carries `id`, `index_url`, `evidence_dir`,
  and `verdict_filename`. The `verdict_filename` is the candidate id slugged to a
  filesystem-safe token (`/` becomes `__`) with a `.json` suffix, because
  web-channel ids are host plus path and contain a `/` that cannot appear in a
  flat file name. Catalog ids have no separator and pass through unchanged.
- WEB-SEARCH gap (filled by Claude Code): the plain CLI invocation runs with an
  empty search function, so it is catalog-only and never invents search hits.
  Under the documented workflow, Claude Code runs the templated per-state queries
  via WebSearch, captures proof evidence (a listing page plus one detail page)
  into each candidate's `evidence_dir` (`data/scout/evidence/<slug>/`), and
  records the results into the registry and worklist.
- `--max-candidates N` (default 50) caps the worklist; anything over the cap is
  deferred and logged, never silently dropped.

County-tier discovery (`casesignal-source-scout discover --state XX --counties`,
or `--state XX`) is NOT yet implemented. It is Tier B, a later sub-project.
Running it today prints an explicit "county-tier discovery not yet implemented
(Tier B); no candidates generated" message and produces no candidates, rather
than silently emitting an empty worklist.

## 2. Classify (Claude Code)

This phase has no CLI subcommand; it is driven by Claude Code once discover has
written the worklist.

For each row in `data/scout/worklist.jsonl`, Claude Code:

1. Builds a subagent prompt with `build_subagent_prompt` (in
   `casesignal.scout.classify`), pointed at that candidate's captured evidence
   in its `evidence_dir`.
2. Dispatches one Agent subagent, which inspects the evidence and returns a
   verdict.
3. Writes the verdict JSON to `data/scout/verdicts/<verdict_filename>`, using the
   exact `verdict_filename` value from the worklist row. Do NOT reconstruct the
   path from a raw candidate id: raw ids can contain `/` and would land in the
   wrong place. The verdict must satisfy `VERDICT_JSON_SCHEMA` (also in
   `casesignal.scout.classify`).

Rejections are written as verdicts too, carrying the gate-fail status and the
reason, so every decision stays auditable.

## 3. Finalize

```
casesignal-source-scout finalize
```

- Reads every verdict from `data/scout/verdicts/`, applies it, estimates case
  counts, scores the surviving candidates, and updates `data/scout/registry.yaml`.
- A candidate that is still a candidate but has no verdict on disk is marked
  needs-review rather than dropped.
- Renders `data/scout/dossier-<date>.md`, where `<date>` is the run date.
- Review the dossier and mark each candidate accepted, rejected, or deferred in
  the registry. Accepted candidates are the input to SP2 (the Adapter Drafter).

## Re-checking rejects

```
casesignal-source-scout recheck rejected
```

Re-queues prior rejects (for example after a gate tweak or a source redesign) by
flipping them back to candidate status. Then re-run the classify phase and
`finalize`.
