"""The seam through which the code-writing agent is invoked — and confined.

A later task points this client at a git worktree and lets it write, with no
human watching, then runs the tests itself and judges the result. Everything the
drafting agent is *able* to do is decided here, so this module is a containment
boundary before it is plumbing.

*Why Bash is absent.* :data:`ALLOWED_TOOLS` names five read-and-write tools and no
way to execute anything. That is the whole basis for the loop's honesty: the agent
cannot run the tests, so "green" is an exit code the loop observed rather than a
claim the model made about its own work. It also cannot reach the network, install
anything, or touch git — which is what keeps ``apply_back`` the only route home.
:data:`DENIED_TOOLS` says the same thing from the other side, because a deny rule
outranks any allow rule wherever it came from.

*Why the ambient configuration is cut off.* ``--allowedTools`` is a permission
list, and permissions merge: this repository's own ``.claude/settings.local.json``
carries dozens of ``Bash(...)`` grants, and the operator's user settings carry
more. ``--restricted`` makes the CLI ignore user, project and local settings files
outright and removes the code-running tools from the built-in set, so Bash is not
merely unpermitted, it is not there. ``--tools`` then fixes the built-in set to
exactly the five we asked for, dropping the harness tools (subagents, worktree
switching, skill loading) that no drafting round needs. ``--strict-mcp-config``
drops ambient MCP servers, which would otherwise contribute tools nothing here
reviewed.

*Why that matters for symlinks.* Task 3 established that a worktree path is not by
itself a containment boundary: an agent that creates a symlink escapes the tree
invisibly, because git does not descend symlinked directories. ``apply_back``
refuses symlinked entries and symlinked destination components, but that only
governs what crosses back; nothing there stops a write from landing outside while
the agent is still running. ``--restricted`` does: it confines the file tools to
the working directories, resolving the path first. Probed against claude 2.1.251
with a symlink pointing out of the working directory, the write was refused with
"... is outside ...; --restricted confines the file tools to the working
directory." That is enforcement by the CLI, not by us, and the limits of it are
written up in the task report — this module cannot verify it in unit tests without
spawning the real binary, so the check remains an upstream behaviour we depend on
rather than one we implement.

*What is enforced here, in-process, before anything is spawned.* The tool list is
refused if it names anything outside :data:`ALLOWED_TOOLS`; the working directory
is resolved through symlinks and must already be a directory; the model may not be
a Haiku; and the timeout must be positive.

*Why the spend ceiling lives here too.* This CLI version has no ``--max-turns``, so
without ``--max-budget-usd`` the wall clock is the *only* bound on a round — and a
loop of three fifteen-minute unattended Opus rounds is a lot of wall clock. A
dollar bound and a time bound are resources of the same kind, and this module
already owns and validates the time one; owning one and deferring the other would
leave the ceiling nobody set. ``max_budget_usd`` defaults to ``None`` so a caller
opts in explicitly, and is validated exactly as ``timeout_s`` is.
"""

from __future__ import annotations

import json
import math
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

# The drafting agent's entire vocabulary. Bash is deliberately absent; see the
# module docstring. Changing this tuple changes what an unattended agent may do,
# so it is asserted directly by tests/unit/drafter/test_client.py.
ALLOWED_TOOLS: tuple[str, ...] = ("Read", "Glob", "Grep", "Write", "Edit")

# Named on ``--disallowedTools`` so the refusal survives any settings file that
# ``--restricted`` might not reach. ``Task`` is here because a subagent is a fresh
# permission context, and a subagent with Bash would undo the whole arrangement.
DENIED_TOOLS: tuple[str, ...] = ("Bash", "Task", "WebFetch", "WebSearch")

# Standing project rule: implementer agents never run on Haiku.
DEFAULT_MODEL = "opus"

_REFUSED_MODEL_MARKER = "haiku"

# How much of a malformed stdout to quote back. Enough to recognise a stack trace
# or an HTML error page, short enough not to paste a whole transcript into a log.
_STDOUT_EXCERPT = 200


@dataclass(frozen=True)
class DrafterResult:
    """One round's outcome.

    ``raw`` is the CLI's own JSON object and nothing else — ``{}`` whenever the
    round produced no parseable object. Diagnostics of ours live in ``text``, so a
    caller reading ``raw`` is always reading the CLI, never a blend of the two.
    """

    ok: bool
    text: str
    raw: dict[str, Any]


class DrafterUnavailable(Exception):
    """Raised when the drafter cannot be run at all: no binary, or no worktree.

    Distinct from a failed round. A round that returns ``ok=False`` can be retried
    with a different prompt; this cannot be retried at all without operator action.
    """


class DrafterMisuse(ValueError):
    """Raised for an invocation this module refuses to build.

    The security-critical member is a tool outside :data:`ALLOWED_TOOLS`: the
    caller supplies ``allowed_tools``, so the constant only binds anything if the
    client refuses to widen past it.
    """


class DrafterClient(Protocol):
    """What the drafting loop depends on. Implemented for real and for tests."""

    def run(
        self,
        prompt: str,
        *,
        allowed_tools: Sequence[str],
        model: str,
        cwd: Path,
        timeout_s: int,
        max_budget_usd: float | None = None,
    ) -> DrafterResult:
        """Run one drafting round in ``cwd`` and report what came back."""
        ...


def _check_invocation(
    allowed_tools: Sequence[str],
    model: str,
    cwd: Path,
    timeout_s: int,
    max_budget_usd: float | None,
) -> Path:
    """Refuse an unsafe or unrunnable invocation; return the resolved workdir.

    The ``cwd`` check is not tidiness. ``subprocess.run`` raises ``FileNotFoundError``
    both for a missing binary *and* for a missing ``cwd``, and the two are
    indistinguishable at the call site — without this pre-check a mistyped worktree
    path is reported as "claude not found on PATH", which sends the operator after
    entirely the wrong problem.
    """
    if not allowed_tools:
        raise DrafterMisuse("refusing to draft with no tools: the agent could not write anything")
    stray = sorted({tool for tool in allowed_tools if tool not in ALLOWED_TOOLS})
    if stray:
        raise DrafterMisuse(
            f"refusing to grant tools outside the drafter allowlist: {', '.join(stray)}. "
            f"Permitted: {', '.join(ALLOWED_TOOLS)}."
        )
    if not model.strip():
        raise DrafterMisuse("refusing to draft without a model")
    if _REFUSED_MODEL_MARKER in model.lower():
        raise DrafterMisuse(
            f"refusing to draft on {model!r}: implementer agents never run on Haiku"
        )
    if timeout_s <= 0:
        raise DrafterMisuse(
            f"timeout_s must be positive, got {timeout_s}; this CLI has no --max-turns, "
            f"so the wall-clock budget is the only thing that ends a wedged round"
        )
    # `not (x > 0)` already refuses NaN, because every NaN comparison is False.
    # isfinite earns its place on infinity alone: `inf > 0` is True, so without it
    # a caller could pass a ceiling that is not one and str(inf) would reach the
    # CLI as the literal "inf". Mutation-checked against max_budget_usd=inf, which
    # is the only value that separates this form from the plain comparison.
    if max_budget_usd is not None and not (
        math.isfinite(max_budget_usd) and max_budget_usd > 0
    ):
        raise DrafterMisuse(
            f"max_budget_usd must be a positive finite number, got {max_budget_usd!r}; "
            f"pass None to run without a spend ceiling"
        )
    # resolve() before is_dir() so a worktree reached through a symlink is named by
    # its real path everywhere: the child's cwd, --add-dir, and whatever the CLI's
    # own confinement compares against.
    workdir = cwd.resolve()
    if not workdir.is_dir():
        raise DrafterUnavailable(
            f"draft worktree {cwd} is not an existing directory; nothing to draft into"
        )
    return workdir


def _parse_stdout(stdout: str) -> tuple[dict[str, Any], str | None]:
    """Return ``(payload, complaint)`` for stdout produced under ``--output-format json``.

    A complaint is not the same as a failed round: on a non-zero exit the CLI's own
    stderr is the better explanation, so the caller decides which to surface.
    """
    if not stdout.strip():
        return {}, "claude produced no output on stdout, though --output-format json was requested"
    try:
        payload = json.loads(stdout)
    except ValueError:
        excerpt = stdout.strip()[:_STDOUT_EXCERPT]
        return {}, f"claude produced output that is not JSON: {excerpt!r}"
    if not isinstance(payload, dict):
        return {}, f"claude produced JSON that is not an object: {type(payload).__name__}"
    return payload, None


def _failure_text(proc: subprocess.CompletedProcess[str], raw: dict[str, Any]) -> str:
    """The most informative account of a failed round that is actually available."""
    for candidate in (proc.stderr, str(raw.get("result") or ""), proc.stdout):
        if candidate.strip():
            return candidate.strip()
    return f"claude exited {proc.returncode} with no output"


class SubprocessDrafterClient:
    """Runs the drafting agent as a child ``claude`` process.

    ``binary`` exists so a caller can point at a specific install; it is never
    taken from the environment, because the whole safety argument rests on which
    program is spawned.
    """

    def __init__(self, binary: str = "claude") -> None:
        self.binary = binary

    def _command(
        self,
        prompt: str,
        allowed_tools: Sequence[str],
        model: str,
        workdir: Path,
        max_budget_usd: float | None,
    ) -> list[str]:
        """Build the argv. The prompt is last, behind ``--``.

        The prompt is a positional and ``-p`` is a boolean flag, so the naive
        placement is right after ``-p``. That works only for prompts that do not
        begin with a dash. Task 13 assembles prompts programmatically, so one
        starting with ``-`` is plausible, and the CLI's parser would read it as an
        unknown option and fail the round opaquely. ``--`` ends option parsing, so
        everything after it is positional whatever it starts with.

        This is not an injection defence — ``subprocess.run`` with a list never
        re-splits an argv element, so a prompt containing ``--allowedTools Bash``
        was already a single inert token. It is purely about the parser.

        Verified against claude 2.1.251: with this exact layout, a prompt beginning
        ``--output-format ...`` was taken as the prompt, and the preceding variadic
        ``--disallowedTools`` stopped at ``--`` rather than swallowing it.
        """
        budget = [] if max_budget_usd is None else ["--max-budget-usd", str(max_budget_usd)]
        return [
            self.binary,
            "-p",
            "--output-format",
            "json",
            "--model",
            model,
            "--permission-mode",
            "acceptEdits",
            "--restricted",
            "--strict-mcp-config",
            *budget,
            "--add-dir",
            str(workdir),
            "--tools",
            ",".join(allowed_tools),
            "--allowedTools",
            *allowed_tools,
            "--disallowedTools",
            *DENIED_TOOLS,
            "--",
            prompt,
        ]

    def run(
        self,
        prompt: str,
        *,
        allowed_tools: Sequence[str],
        model: str,
        cwd: Path,
        timeout_s: int,
        max_budget_usd: float | None = None,
    ) -> DrafterResult:
        """Run one drafting round, returning a failed result rather than raising.

        Every outcome the child can produce is a ``DrafterResult``: a non-zero exit,
        a timeout, an unparseable payload, or an ``is_error`` payload with a zero
        exit. Only a drafter that cannot be run at all raises.
        """
        workdir = _check_invocation(allowed_tools, model, cwd, timeout_s, max_budget_usd)
        cmd = self._command(prompt, allowed_tools, model, workdir, max_budget_usd)
        try:
            proc = subprocess.run(
                cmd, cwd=workdir, capture_output=True, text=True, timeout=timeout_s
            )
        except (FileNotFoundError, PermissionError) as exc:
            # cwd was checked above, so a FileNotFoundError here can only be the
            # binary. The prompt is the last element and is elided: it can be
            # thousands of tokens of source.
            raise DrafterUnavailable(
                f"cannot execute the drafting agent ({exc}); attempted: "
                f"{' '.join(cmd[:-1])} <prompt>"
            ) from exc
        except subprocess.TimeoutExpired:
            return DrafterResult(
                ok=False,
                text=f"the drafting round timed out after {timeout_s}s and was killed",
                raw={},
            )

        raw, complaint = _parse_stdout(proc.stdout)
        if proc.returncode != 0:
            return DrafterResult(ok=False, text=_failure_text(proc, raw), raw=raw)
        if complaint is not None:
            return DrafterResult(ok=False, text=complaint, raw={})
        if raw.get("is_error"):
            return DrafterResult(ok=False, text=_failure_text(proc, raw), raw=raw)
        return DrafterResult(ok=True, text=str(raw.get("result") or ""), raw=raw)


@dataclass
class FakeDrafterClient:
    """A drafting agent scripted as a list of file-writing callables.

    Each ``run`` pops the next callable and applies it to ``cwd``, so a test can
    stage exactly the sequence of edits a real agent would have made across rounds.

    ``prompts`` records what was asked, in order, and a later task asserts a
    security property against it: no expected test value ever appears in a prompt,
    because an agent handed the answer can satisfy the tests without writing a
    parser that works.

    The same refusals as :class:`SubprocessDrafterClient` are applied. A fake that
    accepts what the real client refuses would let the loop's own tests pass with
    Bash in the tool list — precisely the bug those tests exist to catch.
    """

    scripted: Sequence[Callable[[Path], None]]
    prompts: list[str] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)
    _round: int = 0

    def run(
        self,
        prompt: str,
        *,
        allowed_tools: Sequence[str],
        model: str,
        cwd: Path,
        timeout_s: int,
        max_budget_usd: float | None = None,
    ) -> DrafterResult:
        """Apply the next scripted write to ``cwd`` and record the call."""
        workdir = _check_invocation(allowed_tools, model, cwd, timeout_s, max_budget_usd)
        if self._round >= len(self.scripted):
            raise IndexError(
                f"FakeDrafterClient exhausted: {len(self.scripted)} rounds were scripted "
                f"but the loop asked for another"
            )
        action = self.scripted[self._round]
        self._round += 1
        self.prompts.append(prompt)
        self.calls.append(
            {
                "prompt": prompt,
                "allowed_tools": tuple(allowed_tools),
                "model": model,
                "cwd": cwd,
                "timeout_s": timeout_s,
                "max_budget_usd": max_budget_usd,
            }
        )
        action(workdir)
        return DrafterResult(ok=True, text=f"scripted round {self._round - 1}", raw={})
