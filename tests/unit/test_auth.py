import unittest
from typing import Any, cast
from unittest.mock import MagicMock

from fastapi import Request
from sqlalchemy.orm import Session

from casesignal.api.dependencies.auth import require_api_key


class FakeRow:
    def __init__(self, key_id: Any, role: Any = "reader") -> None:
        self.key_id = key_id
        self.role = role


class FakeAuthSession:
    """Session mock for the HMAC-only auth lookup."""

    def __init__(self, key_id: Any = None, role: Any = "reader") -> None:
        self._key_id = key_id
        self._role = role

    def execute(self, statement: Any, params: Any) -> Any:
        sql = str(statement)
        if "key_hmac" in sql:
            outer = self

            class Result:
                def fetchone(self) -> Any:
                    if outer._key_id is None:
                        return None
                    return FakeRow(outer._key_id, outer._role)

            return Result()

        # UPDATE last_used_at — called after a successful lookup
        class VoidResult:
            def fetchone(self) -> Any:
                return None

        return VoidResult()

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass


def _make_request() -> Any:
    """Return a MagicMock that satisfies require_api_key's use of request.state."""
    req = MagicMock(spec=Request)
    req.state = MagicMock()
    return req


def _fake_session(key_id: Any = None, role: Any = "reader") -> Session:
    return cast(Session, FakeAuthSession(key_id=key_id, role=role))


class RequireApiKeyTestCase(unittest.TestCase):
    # test_dev_mode_returns_authenticated_key_with_none was removed in the
    # security remediation (Task 3).  The dev bypass (APP_ENV=dev returning
    # AuthenticatedKey(None, None)) no longer exists; every request must
    # present a valid API key regardless of environment.

    def test_valid_key_returns_authenticated_key(self) -> None:
        from casesignal.api.dependencies.auth import AuthenticatedKey

        req = _make_request()
        result = require_api_key(
            request=req,
            x_api_key="validkey",
            session=_fake_session(key_id=7, role="operator"),
        )
        self.assertIsInstance(result, AuthenticatedKey)
        self.assertEqual(result.key_id, 7)
        self.assertEqual(result.role, "operator")

    def test_missing_key_raises_401(self) -> None:
        from fastapi import HTTPException

        req = _make_request()
        with self.assertRaises(HTTPException) as ctx:
            require_api_key(
                request=req,
                x_api_key=None,
                session=_fake_session(),
            )
        self.assertEqual(ctx.exception.status_code, 401)

    def test_invalid_key_raises_401(self) -> None:
        from fastapi import HTTPException

        req = _make_request()
        with self.assertRaises(HTTPException) as ctx:
            require_api_key(
                request=req,
                x_api_key="badkey",
                session=_fake_session(key_id=None),
            )
        self.assertEqual(ctx.exception.status_code, 401)

    def test_valid_key_sets_api_key_id_on_request_state(self) -> None:
        req = _make_request()
        require_api_key(
            request=req,
            x_api_key="validkey",
            session=_fake_session(key_id=42, role="admin"),
        )
        self.assertEqual(req.state.api_key_id, 42)


class RequireOperatorTestCase(unittest.TestCase):
    def test_operator_role_succeeds(self) -> None:
        from casesignal.api.dependencies.auth import AuthenticatedKey, require_operator

        auth_key = AuthenticatedKey(key_id=1, role="operator")
        result = require_operator(auth_key)
        self.assertIsInstance(result, AuthenticatedKey)
        self.assertEqual(result.role, "operator")

    def test_admin_role_succeeds(self) -> None:
        from casesignal.api.dependencies.auth import AuthenticatedKey, require_operator

        auth_key = AuthenticatedKey(key_id=1, role="admin")
        result = require_operator(auth_key)
        self.assertIsInstance(result, AuthenticatedKey)
        self.assertEqual(result.role, "admin")

    def test_reader_role_fails_403(self) -> None:
        from fastapi import HTTPException

        from casesignal.api.dependencies.auth import AuthenticatedKey, require_operator

        auth_key = AuthenticatedKey(key_id=1, role="reader")
        with self.assertRaises(HTTPException) as ctx:
            require_operator(auth_key)
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(ctx.exception.detail, "Operator privileges required.")


class RequireAdminTestCase(unittest.TestCase):
    def test_admin_role_succeeds(self) -> None:
        from casesignal.api.dependencies.auth import AuthenticatedKey, require_admin

        auth_key = AuthenticatedKey(key_id=1, role="admin")
        result = require_admin(auth_key)
        self.assertIsInstance(result, AuthenticatedKey)
        self.assertEqual(result.role, "admin")

    def test_operator_role_fails_403(self) -> None:
        from fastapi import HTTPException

        from casesignal.api.dependencies.auth import AuthenticatedKey, require_admin

        auth_key = AuthenticatedKey(key_id=1, role="operator")
        with self.assertRaises(HTTPException) as ctx:
            require_admin(auth_key)
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(ctx.exception.detail, "Admin privileges required.")

    def test_reader_role_fails_403(self) -> None:
        from fastapi import HTTPException

        from casesignal.api.dependencies.auth import AuthenticatedKey, require_admin

        auth_key = AuthenticatedKey(key_id=1, role="reader")
        with self.assertRaises(HTTPException) as ctx:
            require_admin(auth_key)
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(ctx.exception.detail, "Admin privileges required.")


if __name__ == "__main__":
    unittest.main()
