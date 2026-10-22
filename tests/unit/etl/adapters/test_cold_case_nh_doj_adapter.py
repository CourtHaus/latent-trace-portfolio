"""NH adapter registry resolution test."""


def test_adapter_registry_resolves_nh() -> None:
    from casesignal.etl.runners.run_pipeline import build_adapter_registry

    reg = build_adapter_registry()
    cls = reg.resolve_class("cold_case_nh_doj")
    assert cls.__name__ == "ColdCaseNhDojAdapter"
