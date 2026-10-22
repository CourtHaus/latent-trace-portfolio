"""Budgeted live transport followed by isolated execution of the actual adapter.

Only trusted source walkers touch the network. Generated code receives a replay
of those fresh responses, so it cannot bypass the request budget or reach a DB.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from casesignal.drafter import runtime, verify, workspace


def probe(ws: workspace.Workspace, brief: dict[str, Any], max_requests: int) -> list[str]:
    adapter = str(brief["adapter_name"])
    if not adapter.isidentifier():
        raise ValueError("invalid adapter name")
    spec = brief.get("runtime")
    if not spec:
        return ["live adapter probe requires a new capture and scaffold (runtime contract missing)"]
    client = runtime.make_client(spec)
    budget = verify.RequestBudget(client, max_requests)
    try:
        with tempfile.TemporaryDirectory(prefix="casesignal-live-") as directory:
            root = Path(directory)
            try:
                held, result = runtime.capture_source(spec, budget, root)
            except Exception as exc:
                return [
                    f"live adapter probe incomplete: {type(exc).__name__}: {exc}",
                    f"{budget.spent} of {budget.limit} budgeted requests used",
                ]
            (root / "fixtures/capture.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "fixtures": [asdict(f) for f in held.fixtures],
                        "detail_sample": len(result.detail_paths),
                    }
                ),
                encoding="utf-8",
            )
            shutil.copytree(
                ws.path / "src", root / "src", ignore=shutil.ignore_patterns("__pycache__")
            )
            (root / "conftest.py").write_text(
                "import sys\nfrom pathlib import Path\n"
                "sys.path.insert(0, str(Path(__file__).parent / 'src'))\n",
                encoding="utf-8",
            )
            (root / "test_live.py").write_text(
                f"""
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
import logging
from casesignal.drafter.runtime import ReplayClient

def test_live_prepare_input():
    module = import_module("casesignal.etl.adapters.{adapter}.adapter")
    from casesignal.drafter.scaffold import class_name_for
    adapter = getattr(module, class_name_for({adapter!r}))(SimpleNamespace(metadata={{}}))
    client = ReplayClient(Path(__file__).parent / "fixtures")
    values = {{}}
    context = SimpleNamespace(logger=logging.getLogger(__name__),
        set_metadata=lambda k, v: values.update({{k: v}}))
    adapter.prepare_input(context, client=client, detail_sample=client.manifest["detail_sample"])
    assert set(client.requested) == set(client.fixtures)
    assert any(isinstance(value, list) and len(value) == {result.records_captured}
               for value in values.values())
""",
                encoding="utf-8",
            )
            outcome = verify.run_pytest([Path("test_live.py")], root)
            return [
                f"live adapter prepare_input: {outcome.verdict}; {result.records_captured} captured records",
                f"{budget.spent} of {budget.limit} budgeted requests used",
            ]
    finally:
        budget.close()
