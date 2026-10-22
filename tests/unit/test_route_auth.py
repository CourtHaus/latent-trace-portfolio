from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute

from casesignal.api.app import create_app
from casesignal.api.dependencies.auth import require_admin, require_api_key
from casesignal.api.dependencies.operator_auth import require_operator_admin


def _find_route(path: str, method: str) -> APIRoute:
    app = create_app()
    for route in app.routes:
        if isinstance(route, APIRoute) and route.path == path and method in route.methods:
            return route
    raise AssertionError(f"Route not found: {method} {path}")


def _dependency_calls(dependant: Dependant) -> set[object]:
    calls: set[object] = {dependency.call for dependency in dependant.dependencies}
    for dependency in dependant.dependencies:
        calls.update(_dependency_calls(dependency))
    return calls


def _assert_public(path: str, method: str = "GET") -> None:
    route = _find_route(path, method)
    deps = _dependency_calls(route.dependant)
    assert require_api_key not in deps, f"{method} {path} should be public (no require_api_key)"
    assert require_admin not in deps, f"{method} {path} should be public (no require_admin)"


def test_cold_cases_map_is_public() -> None:
    _assert_public("/api/v1/cold-cases/map")


def _assert_admin(path: str, method: str) -> None:
    route = _find_route(path, method)
    assert require_admin in _dependency_calls(
        route.dependant
    ), f"{method} {path} should be admin-only (require_admin)"


def _assert_operator_admin(path: str, method: str) -> None:
    route = _find_route(path, method)
    deps = _dependency_calls(route.dependant)
    assert require_operator_admin in deps
    assert require_admin not in deps
    assert require_api_key not in deps


def test_admin_key_management_routes_require_admin_role() -> None:
    _assert_admin("/api/v1/admin/keys", "POST")
    _assert_admin("/api/v1/admin/keys", "GET")
    _assert_admin("/api/v1/admin/keys/{key_id}", "DELETE")


def test_admin_ingestion_routes_require_admin_role() -> None:
    _assert_admin("/api/v1/admin/ingestion/uploads", "POST")
    _assert_admin("/api/v1/admin/ingestion/runs", "POST")
    _assert_admin("/api/v1/admin/ingestion/runs/{ingestion_run_id}", "GET")
    _assert_admin("/api/v1/admin/ingestion/dataset-versions/{dataset_version_id}/publish", "POST")
    _assert_admin("/api/v1/admin/ingestion/dataset-versions/{dataset_version_id}/unpublish", "POST")


def test_operator_snapshot_requires_supabase_operator_admin() -> None:
    _assert_operator_admin("/api/v1/operator/snapshot", "GET")
