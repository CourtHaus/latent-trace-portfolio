"""SourceAdapter ABC — 5-stage contract."""

from __future__ import annotations

import inspect


def test_abstract_methods_are_the_5_stages() -> None:
    from casesignal.etl.adapters.base import SourceAdapter

    abstracts = SourceAdapter.__abstractmethods__
    assert abstracts == {
        "adapter_name",
        "prepare_input",
        "register_source",
        "load_raw",
        "transform",
    }


def test_publish_is_concrete_with_default_impl() -> None:
    from casesignal.etl.adapters.base import SourceAdapter

    publish = SourceAdapter.publish
    assert "abstractmethod" not in repr(publish)
    src = inspect.getsource(publish)
    assert "publish_dataset" in src


def test_no_legacy_stages_remain() -> None:
    from casesignal.etl.adapters.base import SourceAdapter

    abstracts = SourceAdapter.__abstractmethods__
    for legacy in (
        "initialize_input",
        "transform_core",
        "validate_raw",
        "validate_core",
        "derive_fields",
        "cleanup",
    ):
        assert legacy not in abstracts, f"{legacy} should not be in new contract"
