"""No unit test in this package may spawn the drafting agent.

Before this guard existed, "the tests never invoke the real binary" held only as a
*consequence* of the implementation being correct, which is backwards for a module
whose job is to decide what an unattended agent may do. Delete any refusal branch
in ``client._check_invocation`` and the refusal tests stop raising, fall through to
``subprocess.run``, and launch a real, billable, network-reaching ``claude -p`` in a
pytest ``tmp_path``. That is not hypothetical: a mutant with the Haiku guard removed
did exactly that, taking 3.46s against 0.07s for every other mutant in the run.

The project is self-funded and CI runs unattended, so the failure mode of a
regressed guard is a test suite that quietly buys agent sessions instead of going
red. This fixture inverts that: spawning is denied by default, so a regression
fails loudly and instantly.

"By default" is a claim about CALL SHAPES as well as about programs, and it used to
be true only of ``subprocess.run``. ``subprocess.Popen``, ``call``, ``check_call``,
``os.system`` and ``os.posix_spawn`` walked straight past it, so a future spawn site
written with any of them would not have been denied -- it would have spawned,
silently and billably, which is exactly the "held only as a consequence of the
implementation being correct" shape this docstring argues against. Every one of them
is patched now, through one shared decision function, and the list is asserted
against a live probe of each entry point rather than trusted. ``check_output`` needs
no entry of its own: it calls the module-global ``run``.

The allowlist is ``git`` alone, and it is a pass-through rather than a fake, because
``workspace.py`` genuinely shells out to git and its tests exercise real worktrees.
Deny-by-default with one named exception is the whole rule; if a later module in
this package needs another program, adding it here should be a deliberate edit with
a reason, not a silent widening.

There is now a second exception, and this paragraph is the deliberate edit the rule
above asks for. ``verify.run_pytest`` shells out to ``[sys.executable, "-m",
"pytest", ...]``, and its whole job is to tell four different non-zero exits apart --
a red test from an unimportable module from an empty collection. Modelling those exits
with a fake ``subprocess.run`` would test my model of pytest rather than pytest, and
the specific defect being guarded against (``rc != 0`` read as success, ``rc == 5``
read as a kill) is a defect in exactly that model. So the exception is written as
narrowly as it can be: not "python", but *this* interpreter invoked as ``-m pytest``.
It does not widen anything that matters. The refusal it exists to protect is
``client._check_invocation``, which spawns ``claude``; a program named ``claude`` is
still denied, as is this interpreter running anything other than pytest.

A test that patches ``subprocess.run`` itself still wins — ``monkeypatch`` undoes in
LIFO order, so the in-test patch shadows this one for that test and is restored
first. The guard therefore constrains the tests that *forgot*, not the ones that
staged a fake on purpose.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

# Captured at import, before any fixture has had a chance to replace it.
_REAL_RUN = subprocess.run
_REAL_POPEN = subprocess.Popen
_REAL_CALL = subprocess.call
_REAL_CHECK_CALL = subprocess.check_call
_REAL_SYSTEM = os.system
_REAL_POSIX_SPAWN = getattr(os, "posix_spawn", None)

# Every way this interpreter can start a process, with the real callable to delegate to
# once the command has been allowed. ``subprocess.check_output`` is deliberately absent:
# it calls the module-global ``run``, so patching it as well would double-check one
# command and prove nothing. ``os.exec*`` is absent for the opposite reason -- it
# REPLACES this process rather than spawning beside it, so a test that reached one would
# take the whole pytest session with it and could not be silent about anything.
_SPAWN_ENTRY_POINTS: tuple[tuple[Any, str, Any], ...] = tuple(
    entry
    for entry in (
        (subprocess, "run", _REAL_RUN),
        (subprocess, "Popen", _REAL_POPEN),
        (subprocess, "call", _REAL_CALL),
        (subprocess, "check_call", _REAL_CHECK_CALL),
        (os, "system", _REAL_SYSTEM),
        (os, "posix_spawn", _REAL_POSIX_SPAWN),
    )
    if entry[2] is not None
)

# Programs a unit test in this package may really execute.
_PERMITTED_PROGRAMS = frozenset({"git"})


def _is_this_interpreter_running_pytest(cmd: Any) -> bool:
    """The one shape ``verify.run_pytest`` builds, and nothing broader.

    Matched on the interpreter path AND on ``-m pytest`` together, so this
    interpreter running ``-c`` or a script, or any other interpreter running
    pytest, is still refused.
    """
    if not isinstance(cmd, (list, tuple)) or len(cmd) < 3:
        return False
    return [str(part) for part in cmd[:3]] == [sys.executable, "-m", "pytest"]


class SpawnedOutsideTheHarness(AssertionError):
    """Raised when a unit test tries to execute a program it never staged a fake for."""


def _refuse_unless_permitted(cmd: Any) -> None:
    """Raise unless ``cmd`` names one of the two things this package may really run.

    ``cmd`` arrives in three shapes: an argv sequence (``subprocess.*``), a shell string
    (``os.system``), and a program path (``os.posix_spawn``). A shell string is split on
    whitespace and only its first token is read -- enough to name the program in the
    refusal, and the refusal is the default anyway, so a string this misreads is refused
    rather than waved through.
    """
    if isinstance(cmd, (list, tuple)):
        first = cmd[0] if cmd else ""
    elif isinstance(cmd, str):
        first = cmd.split()[0] if cmd.split() else ""
    else:
        first = cmd
    program = Path(str(first)).name
    if program in _PERMITTED_PROGRAMS or _is_this_interpreter_running_pytest(cmd):
        return
    raise SpawnedOutsideTheHarness(
        f"a unit test tried to execute {program!r} for real "
        f"({first!r}). Unit tests must monkeypatch the spawn they drive; only "
        f"{sorted(_PERMITTED_PROGRAMS)} and this interpreter running "
        f"'-m pytest' may actually be spawned here. If this "
        f"fired from a drafter refusal test, a guard in "
        f"client._check_invocation has regressed and the round would have "
        f"been billed."
    )


@pytest.fixture(autouse=True)
def _refuse_unexpected_spawns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deny every subprocess in this package except git and this interpreter's pytest.

    Every spawn entry point in :data:`_SPAWN_ENTRY_POINTS`, not just
    ``subprocess.run``: the module docstring calls this a structural deny-by-default,
    and a guard that only knows one call shape is not one.
    """

    def guard(real: Any) -> Any:
        def guarded(cmd: Any, *args: Any, **kwargs: Any) -> Any:
            _refuse_unless_permitted(cmd)
            return real(cmd, *args, **kwargs)

        return guarded

    for module, name, real in _SPAWN_ENTRY_POINTS:
        monkeypatch.setattr(module, name, guard(real))
