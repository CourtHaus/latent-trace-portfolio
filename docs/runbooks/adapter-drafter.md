# Adapter Drafter runbook

The Adapter Drafter (SP2) turns an accepted Source Scout candidate into a
machine-drafted source adapter: it captures the source's own pages, has an agent
read them, measures what it read against the captured records, generates the
package and the tests, has a second agent write the parser inside a throwaway git
worktree, runs the generated tests over it, and opens a pull request for review.

Two of its passes are agent rounds (`claude -p`, restricted to file tools). The
rest is Python. The pipeline does not persist cases to the database. Capture and
live verification fetch sources; hosted agent calls and finish/push/PR operations
also use the network.

Run source capture and drafting in a private operator checkout. Generated source
fixtures require a separate content review before inclusion in this portfolio
repository; its CI rejects additional fixture files until explicitly reviewed.

The entry point is `casesignal-adapter-draft`. All runtime state lives under
`data/drafts/<adapter>/` (git-ignored).

Read this before the first run: **a draft is a proposal, not a change that has
been checked.** The tests it ships were written by a generator from a measurement,
and the parser under them was written by an agent. Review it as you would a pull
request from a stranger.

## The operator loop

```
casesignal-adapter-draft claim    <candidate-id> --branch draft/<adapter>
casesignal-adapter-draft capture  <candidate-id>
casesignal-adapter-draft scaffold <adapter>
casesignal-adapter-draft draft    <adapter>
casesignal-adapter-draft verify   <adapter> [--live-check]
casesignal-adapter-draft finish   <adapter>
```

`run <candidate-id>` chains `claim` through `verify` in one process. It stops
before `finish`, because `finish` commits, **pushes**, and opens a pull request;
add `--finish` to include it. `--finish` is asked for before the verdict exists,
so a chained run that resolves `FAIL` stops there and does not push: read the
verdict, then run `finish <adapter>` yourself if you mean to ship a red draft for
a human to complete. `finish` typed by hand is never second-guessed.

Before you start, know two things:

- **Which branch the draft lands on.** `finish` commits into your checkout and
  pushes it. The draft's own worktree branch is a different branch and is
  destroyed after success. The destination is pinned in the claim lease; switching
  to any other branch causes finish to refuse before applying changes.
  `claim` settles this: pass `--branch draft/<adapter>` and it creates or checks
  that branch out. Standing on a protected branch with no `--branch` is refused
  before anything is spent. The protected list is `main`, `master`, the remote's
  default, anything in `git config casesignal.drafter.protected`, and anything in
  `CASESIGNAL_DRAFTER_PROTECTED_BRANCHES`. That last pair is the escape hatch, and
  the same list is enforced again inside `finish`.
- **Your working tree has to be clean.** `claim` refuses an uncommitted or staged
  checkout. `finish` commits with `git commit -- <paths>`, which protects the
  *commit* from your work in progress but not your *index* from our `git add`.
  Commit or `git stash` first.

## 1. `claim`

```
casesignal-adapter-draft claim ok__osbi --branch draft/cold_case_ok_osbi
```

Prints the **derived adapter name** first, before anything is spent. Read it. The
naming rule is `cold_case_<state>_<agency-acronym>` with no exceptions, and it
disagrees with seven of the eleven adapter names already in the repository
(`wy_dci`, `oh_ag`, ...). If you want a different one, re-run with
`--adapter-name`; every later subcommand is keyed on it.

Then, still before anything is spent, it refuses the two collisions the adapter
name settles on its own: a `tests/fixtures/<adapter>` this pipeline did not write
(the `scaffold` pass PRUNES that directory), and a generated target that already
exists and is not an unmodified product of the generator (re-drafting over an
adapter somebody has since edited by hand). Both are re-checked at their own stage
too; they are asked here because on the `run` chain everything after this costs a
crawl and a paid reader round.

Then: reports any drafting worktree left over from an earlier run, refuses a
dirty checkout or a staged index, settles the branch, and takes the lease on
`data/drafts/<adapter>/`. One draft per adapter at a time; `--force` breaks a
stale lease (a run killed mid-flight leaves one behind).

## 2. `capture`

```
casesignal-adapter-draft capture ok__osbi
```

Three things happen in one process, and they are one command because the second
and third read data the first holds only in memory:

1. **The capture.** Walks the listing exhaustively, samples detail pages, writes
   fixtures and a manifest. One host is allowlisted and robots is never bypassed.
   A 403 that looks like a TLS fingerprint block is retried once over `curl_cffi`
   and the adapter is drafted for that transport.
2. **The reader pass** (agent round 1). Reads disposable fixture copies and writes
   `locators.json` (how to find each field) and `expectations.json` (golden values
   transcribed off three records by hand). Both original and copied bytes are
   checked before accepting its outputs. It is told never to infer race.
3. **The inventory pass.** Applies every locator to every captured record, counts
   the hits, and rewrites `brief.json` with `inventory_measured: true`, the
   measured coverage, and the derived floors. **This is the pass everything
   downstream trusts.** A structured field gets measured coverage times 0.95; a narrative
   field gets its measured coverage minus 0.10. Source completeness and parser
   retention are distinct: missing source values are not parser failures.

Flags worth knowing:

- `--detail-sample N` (default 12) -- how many detail pages to fetch. The sample
  spans the listing rather than taking its head.
- `--session-id S` -- resume a named capture session, refusing if the draft
  directory holds a different one. Without it a manifest already on disk is
  continued.
- `--refresh` -- start a new session regardless.
- `--accept-partial {count_mismatch,empty,truncated,unidentified}` -- the capture
  refuses four results that look like data and are not: an empty corpus, a walk
  that stopped while the source was still offering more, rows whose record list
  nobody could identify, and a corpus the source's own published count disagrees
  with. Read the fixtures first. Every refusal names the exact token that clears
  it, so you do not have to come back here for it. Nothing is accepted by default,
  and every acceptance is recorded in `brief.json` so it travels with the artefact.

  `count_mismatch` is the one worth reading twice. Source Scout recorded how many
  cases the source says it has; if the walk came back with markedly fewer, two
  sources disagree about the size of this source and the capture is the one that
  can be wrong quietly. How much slack there is depends on how the Scout got the
  number: none for an `exact` count, 25% for a `probed` one, 50% for one `visible`
  on the page. Accept it only when the source's number is the stale one.

  Know what `exact` actually is before you trust or distrust a refusal from it. For
  a Socrata or ArcGIS candidate it is a catalog row count. For a **web** candidate
  -- which is most of them -- the only route to `exact` is a regex over page-1 HTML
  matching "*<a> to <b> of <N>*" or "*of <N> results*", scraped at scout time and
  frozen there. It can count a superset, it can have drifted since, and it can have
  matched something that was never a case count. Zero slack is still right, because
  a published number is the strongest outside evidence there is and the refusal is
  cheap to clear -- but the refusal is not proof that your capture is short.
- `--model`, `--timeout-s`, `--max-budget-usd` -- the agent round's bounds. The
  budget is not decoration: the CLI has no `--max-turns`, so apart from the wall
  clock it is the only bound there is.

Read the advisories it prints. `derived a floor of 0.0` is the important one: that
field's generated test cannot fail, and no other layer will mention it again.

## 3. `scaffold`

```
casesignal-adapter-draft scaffold cold_case_ok_osbi
```

Generates, into your checkout:

- `src/casesignal/etl/adapters/<adapter>/` -- `adapter.py` (with `parse_records`
  and `parse_detail` as raising stubs), `register.py`, `raw_load.py`
- `tests/unit/etl/adapters/test_<adapter>_invariants.py` -- the structural
  invariants and one coverage-floor test per measured field
- `tests/unit/etl/adapters/test_<adapter>_expectations.py` -- the golden values
- `tests/fixtures/<adapter>/` -- the capture's fixtures, copied where both
  generated modules look for them. Exactly the pages `brief.json` names, and
  nothing else: a re-`scaffold` after a `capture --refresh` deletes the fixtures
  the superseded capture left behind, which would otherwise ship in the pull
  request and read as current evidence. Because that directory is **pruned**,
  `scaffold` refuses one it did not write itself -- it leaves a `.drafted-by`
  marker in the directory and looks for it before deleting anything, so a directory
  it did not create is refused rather than emptied.
- `docs/drafts/<adapter>.md` -- the memo: source facts, page shapes, the measured
  inventory, the capture's gotchas
- an entry in `src/casesignal/etl/sources/cold_case_<state>.yaml`
- a registration in `src/casesignal/etl/runners/run_pipeline.py`

There are two ways to hit that fixtures-directory refusal, and the answer is
different for each:

- **The name collides with another suite's fixtures.** `tests/fixtures/` holds
  `fdle`, `scout`, `html` and `xml` under plain names. None of them is an adapter
  package, so nothing else would have stopped `--adapter-name fdle`. Draft under a
  different name.
- **You are re-drafting an adapter that already shipped.** `tests/fixtures/` also
  holds `cold_case_ar_asp`, `cold_case_mn_bca`, `cold_case_nh_doj` and
  `cold_case_ok_osbi`, whose fixtures are curated and are read by those adapters'
  own hand-written tests. This is the collision you are most likely to hit. Keep the
  name: the draft is meant to be called that. But move the directory aside or delete
  it yourself first, deliberately -- replacing those fixtures with the ones this
  capture walked is a change for a reviewer to look at, not a retry.

Every generated file ends in a `drafted-by:` marker whose digest covers the text
above it. Edit a generated file and it stops verifying, which is exactly when it
must stop being regenerated -- so a **re-draft over an edited file is refused**,
with a message that says somebody has edited it. That is correct and it will
still surprise you: the parser pass edits `adapter.py`, so re-drafting an adapter
that has already been through `draft` always hits it. Delete the package (or draft
under another name) before re-running.

`run_pipeline.py` is the one file a draft **shares** with the rest of the
repository. Any unrelated uncommitted edit of yours in it is committed with the
draft.

## 4. `draft`

```
casesignal-adapter-draft draft cold_case_ok_osbi --rounds 3
```

Cuts a git worktree at `.worktrees/<adapter>` on branch `drafts/<adapter>`, stages
the scaffold into it and commits it there, then runs the parser pass (agent round
2) up to `--rounds` times. After each round the generated tests are run in the
worktree and the failure lines are fed back into the next prompt, redacted so no
transcribed value can be quoted back to the agent.

Everything the scaffold wrote is staged into the worktree **except**
`test_<adapter>_expectations.py`. That module stays in your checkout and is
injected only for the duration of each test run. It is the answer key; an agent
that could read it would satisfy every golden test by hardcoding.

The worktree's `tests/conftest.py` is replaced with one that keeps the `sys.path`
insertion and drops the test-database redirection. The generated modules touch no
database, and the repository's own guard would fail the whole round with a pytest
usage error on any machine where Postgres is down.

The loop stops early on `green` (tests pass), `no-progress` (two rounds produced
the same failures), `timeout`, or one of three run-ending conditions --
`wrote-outside-allowlist`, `deleted-in-workspace`, `unsupported-entry` -- each of
which means the draft can no longer be applied back and further rounds would be
bought for nothing.

`draft` refuses **before** it cuts the worktree or checks out the destination
branch if the scaffold is not in your checkout -- the adapter package, the
invariant module and the golden module. That is the state you are in after
skipping `scaffold`, and after deleting the adapter package to clear a refused
re-draft. Nothing is spent either way; the refusal is what keeps the retry from
needing a worktree cleanup first.

`--rounds` has a ceiling (`loop.MAX_ROUNDS`), and so does what one run may cost at
the per-round budget it was handed (`loop.MAX_RUN_BUDGET_USD`). `--max-budget-usd`
bounds ONE round, so without these a mistyped digit is that many unattended agent
sessions. Both refuse before the lease and the worktree on `draft`, and before the
crawl and the reader round on `run`. If you mean it, re-run
`draft` when the first batch is spent; it resumes the same worktree.

`--dry-run` prints round 0's prompt and exits without a worktree, a lease, or an
agent. Use it to see exactly what the agent is told. It is a `draft` flag: `run
--dry-run` is refused, because the prompt is rendered from a measured brief and
`run` has no brief yet -- building one crawls the whole source and buys a real
reader round, which is not a dry run. Run `capture` first, then `draft <adapter>
--dry-run`.

## 5. `verify`

```
casesignal-adapter-draft verify cold_case_ok_osbi --live-check
```

Grading requires **Linux with Landlock ABI 3+ (kernel 6.2+) and libseccomp**.
Unsupported hosts fail closed; use a suitable Linux development environment. The
child gets an allowlisted environment, a read-only worktree and Python runtime,
and disposable writable scratch space. Host home files and the operator checkout
are not granted. Network, process creation and tracing are denied; CPU, address
space and file sizes are bounded. No database credentials are passed.

The generated tests replay the capture through the actual `prepare_input`, check
listing/detail joins, and validate pure canonical mapping plus transform wiring.
They do **not** certify database persistence or a successful live ingestion.
Containment does not make pytest's in-process reporting immune to a deliberately
adversarial module; review the generated code before accepting a draft.

Runs the two generated modules separately in the worktree, scans **both**
`scrape.py` and `transform.py` for marked `TODO(field):` claims, and resolves one
of three statuses:

| Status | Meaning |
| --- | --- |
| `PASS` | Both modules green, no marked TODOs, no floor that cannot fail. |
| `PASS_WITH_TODOS` | Both modules green, and the parser left at least one `TODO(field):` saying it could not extract something. **The tests do not cover that field.** Read every TODO in the pull request body before believing the green. |
| `FAIL` | A module failed, skipped assertions, did not run, or a required field has a TODO or vacuous floor. Optional vacuous floors produce `PASS_WITH_TODOS`. |

"Did not run" is not "failed", and the report says which: a module that will not
import produces no failures and no passes, and a report that called that green
would be the exact defect this pipeline exists not to have.

`--live-check` walks the current source under `--max-requests` (default 5), then
runs the actual generated `prepare_input` in isolation against those fresh responses.
The trusted HTTP broker enforces the budget; generated code cannot open sockets.
This is advisory and never changes the offline status. A budget exhausted before
the walk finishes is reported as incomplete, not as a successful adapter probe.
Results are saved in `live.json`; only results for the current adapter digest and
capture session are carried into a later finish report.

## 6. `finish`

```
casesignal-adapter-draft finish cold_case_ok_osbi
```

Copies the parser out of the worktree into your checkout (refusing the whole draft
if it wrote anywhere outside its own package, deleted a tracked file, or wrote a
symlink), stages the draft's own paths, commits, pushes, and opens a pull request
whose body carries the verdict, the round-by-round history, the TODOs and the
measured coverage -- and never a failure line, because those quote golden values.

On success it destroys the worktree, writes `outcome.json`, and releases the lease.
A commit, push, or PR failure retains the worktree and lease. Fix the reported
problem and retry `finish`; the existing draft and commit are reused.

`finish`'s pre-flight refusals -- an unusable brief, an unreadable branch, a
detached HEAD, a protected branch -- all leave the lease **held** on purpose: the
draft is still live in its worktree and the lease is what stops a second run
drafting over it. Fix what the message names and re-run `finish`; it costs nothing
and re-drafts nothing. If you are abandoning the draft instead, delete
`data/drafts/<adapter>/lease.json`. That is the only remedy: `finish` has no
`--force`, and `claim --force` cannot free it either, because `claim` refuses a
dirty checkout before it reaches the lease and by now the scaffold's own output has
made yours dirty.

The exit message names **which branch the commit landed on** and whether it was
pushed. That is your checkout's branch, not the draft's worktree branch. If a
`gh pr create` fails after the push, that commit is on the remote and the message
says so.

If a pull request is already open, `finish` checks its head branch, open state,
and adapter identity marker before updating its title and body. An unrelated PR
is refused. The proposed body is also saved in `data/drafts/<adapter>/pr-body.md`.

## What is under `data/drafts/<adapter>/`

| File | What it holds |
| --- | --- |
| `.lease.lock` | Serializes concurrent claim attempts; it may remain after release. |
| `live.json` | Advisory live probe, bound to capture session and adapter digest. |
| `lease.json` | Who is drafting this adapter, from where, since when. |
| `manifest.json` | The capture session: every fixture, its URL, its status and its sha256. |
| `fixtures/` | The captured pages themselves. |
| `locators.json` | The reader pass's output: how to find each field. |
| `expectations.json` | The reader pass's golden values for three records. |
| `brief.json` | The whole capture plus the measurement. `inventory_measured`, `floors`, `coverage`, `vacuous_floors`, `unreachable_floors`, `omitted_fields`, `accepted_findings`. |
| `expectation_module.py` | The golden module the loop injects, with its fixtures root rewritten to an absolute path. Not the file the pull request ships. |
| `workspace.json` | Which worktree and branch this draft's parser lives in. |
| `loop.json` | Every round's verdict and redacted failure signature. |
| `rounds/NN/` | Per round: `prompt.md`, the agent's own reply, `pytest.txt`, `result.json`. |
| `pr-body.md` | Exactly what was published as the pull request body. |
| `outcome.json` | What the finishing run did: the pull request, the branch it committed to, whether it pushed, whether the worktree was kept, and every warning. |

**`rounds/NN/pytest.txt` holds the transcribed golden values verbatim.** So does
`expectations.json`. `data/drafts/` is git-ignored for that reason; do not commit
it and do not paste a round transcript into an issue.

## When something refuses

Every refusal is printed as `FAIL [<stage>] <Type>: <message>` and the stage names
the pass to re-run.

| Stage | What it means | What to do |
| --- | --- | --- |
| `cli` | The run was not startable: a dirty checkout, a staged index, a protected branch, a missing lease, a missing brief, a `draft` with no scaffold under it. | The message names the fix; nothing was spent. |
| `claim` | The lease is held by another run. | Check the pid and host it names. `--force` if it is stale. |
| `capture` | The candidate is out of scope (not accepted, a gate failed, needs JavaScript, a PDF, not https), or what came back is not fit to draft against. | Scope refusals are final. Quality refusals name a finding you can accept with `--accept-partial` once you have read the fixtures. |
| `reader` | The reader round failed, or wrote something unusable: a locator for a field nobody asked for, a malformed file. | Re-run `capture`. The fixtures are already on disk, so it resumes. |
| `inventory` | The measurement cannot be trusted: a locator matched nothing, a locator names a page this capture holds no records from, or the derived floors assert nothing. | The message names the field. Usually the locator is wrong; re-run `capture`. |
| `scaffold` | The generator will not write: a generated module did not parse, or a target file exists and is not an unmodified product of this generator. | Delete or move the edited file, or draft under another `--adapter-name`. |
| `draft` | The loop refused to start or ended a run: the worktree was already dirty, a test path was missing, the golden values were already in the tree, or the agent wrote outside its allowlist. | Read `loop.json` and `rounds/NN/result.json`. An intact recorded worktree can resume; inspect invalid changes before retrying. |
| `workspace` | A worktree or branch for this adapter already exists. | See "clearing a kept worktree" below. |
| `verify` | The brief claims to be measured over floors that say nothing, or there is no `transform.py` at all -- which means no parser was written. | An unmeasured brief means re-running `capture`. A missing `transform.py` means the loop never produced anything; read the round transcripts. |
| `pre-flight` | `finish` refused before touching anything: a protected branch, a detached HEAD, a brief with no adapter name. | Check a branch out and re-run `finish`. Nothing was half-done. |
| `apply-back` | The draft wrote outside its allowlist, deleted a tracked file, or produced a symlink. | The worktree is **kept** so nothing is lost. Inspect it, then clear it. |
| `finish` | The commit, push, or pull request failed. | Read `outcome.json`: it names the branch the commit landed on and whether it was pushed. |

## Abandoning a kept worktree

A finished draft destroys its worktree and keeps the branch. A refused apply-back
keeps **both**, on purpose: nothing ever commits inside a drafting worktree, so
`git worktree remove --force` there would delete agent-written work that cost real
money. `claim` and `draft` report every kept worktree they find.

Retry `finish` after a transport failure, or `draft` to resume an intact workspace.
Only clear it when deliberately abandoning the generated work. A fresh
`workspace.create` refuses the same adapter name until both are gone, and the order
matters, because git will not delete a branch a worktree is still using:

```
git worktree remove --force .worktrees/<adapter>
git branch -D drafts/<adapter>
```

Then re-run `draft`. If the scaffold's own output is still in your checkout from
the refused run, `scaffold` will refuse to overwrite `adapter.py` -- the parser pass
edited it, so it no longer verifies as generated. Delete the adapter package first.

## Reviewing the pull request

The body is written to be read in this order: the verdict, then what the drafter
itself is unsure about, then the rounds, then the TODOs, then the measured
coverage, then the provenance. Three things deserve a second look every time:

- **`PASS_WITH_TODOS`.** Each TODO is a field the parser said it could not extract.
  Nothing tests those fields.
- **A field named under "no floor can grade this".** Its coverage test was not
  rendered at all, because a floor of 0.0 is satisfied by a parser that never
  extracts the field.
- **The census note in the invariant module.** If the capture was not exhaustive,
  no exact-count assertion was rendered, and the record-level tests are statements
  about a *sample*.

Then run the generated tests yourself, read `docs/drafts/<adapter>.md`, and treat
`transform.py` as the part a human still owns.

## Known limits

These are properties of the tool as shipped, not bugs to report. Each was found
during the build, verified, and left in deliberately.

**A census is refused more often than it is wrong.** Where the drafter cannot
establish that a listing walk finished, it records an unknown total rather than
claiming a complete one. A false census would license an exact-count invariant
that any parser satisfies trivially, so the trade runs one way on purpose: you
will meet refusals on healthy sources, each naming the `--accept-partial` token
that proceeds past it. Known shapes that refuse today:

- A listing whose records are bare `<article>` elements, because that is also the
  shape of a single record wrapping many rows. Proceed with
  `--accept-partial unidentified`.
- A feed whose whole corpus happens to equal its own page size, which is
  indistinguishable from the first page of a longer feed.
- A catalog count that disagrees with what was captured, including a count that
  is stale *high*. Proceed with `--accept-partial count_mismatch`.

**Records nested more than four containers deep lose their census** at any corpus
size. GeoJSON `FeatureCollection` payloads and ArcGIS-shaped responses are the
known cases. The walk still captures the records and coverage is still measured;
only the completeness claim is dropped, so the generated tests describe a sample.
This is a capability limit, not a correctness risk, and it is the first thing to
revisit before drafting an ArcGIS or GeoJSON source.

**The `probed` tolerance rung described under `verify` cannot currently fire.**
The wording outruns the code.

**Production traversal is conservative.** It uses the capture walkers to discover
current pages and refuses truncated or unidentified walks. JSON feeds have a 5,000
record safety cap. Capture-time `--accept-partial` does not silently authorize
partial production ingestion; unsupported sources need a reviewed custom adapter.

**The automated end-to-end tests use fake agents and HTTP responses.** They run
real Git worktrees, isolated pytest, and a local bare-remote push/retry. GitHub PR
responses are faked. A paid Claude pilot and database persistence validation remain
operator checks before shipping a newly generated adapter.
