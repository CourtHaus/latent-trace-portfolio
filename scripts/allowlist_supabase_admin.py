from __future__ import annotations

import argparse
import os
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.sql.base import Executable


class AuthUserRow(Protocol):
    @property
    def id(self) -> object: ...

    @property
    def email(self) -> str: ...


class AdminUserRow(Protocol):
    @property
    def supabase_user_id(self) -> object: ...


class ExecuteResult(Protocol):
    def one_or_none(self) -> AuthUserRow | None: ...

    def all(self) -> Sequence[AdminUserRow]: ...


class SessionLike(Protocol):
    def execute(
        self,
        statement: Executable,
        params: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
    ) -> ExecuteResult: ...

    def commit(self) -> None: ...


def allowlist_admin_user(session: SessionLike, *, email: str, enabled: bool = True) -> str:
    normalized_email = email.strip().lower()
    if not normalized_email:
        raise RuntimeError("Email must not be blank.")

    row_result = session.execute(
        text(
            "SELECT id::text AS id, email"
            " FROM auth.users"
            " WHERE LOWER(email) = :email"
            " ORDER BY created_at DESC"
            " LIMIT 1"
        ),
        {"email": normalized_email},
    )
    auth_user = row_result.one_or_none()
    if auth_user is None:
        raise RuntimeError(
            "No Supabase Auth user found for that email. Create the user in "
            "Supabase Authentication first, then rerun this script."
        )

    params = {
        "user_id": auth_user.id,
        "email": auth_user.email,
        "normalized_email": normalized_email,
        "enabled": enabled,
    }
    existing_result = session.execute(
        text(
            "SELECT supabase_user_id::text AS supabase_user_id"
            " FROM app_auth.admin_user"
            " WHERE supabase_user_id = CAST(:user_id AS uuid)"
            " OR LOWER(email) = :normalized_email"
            " FOR UPDATE"
        ),
        params,
    )
    existing_user_ids = {str(row.supabase_user_id) for row in existing_result.all()}
    if len(existing_user_ids) > 1:
        raise RuntimeError(
            "Conflicting admin allowlist rows match this Supabase user/email; "
            "repair app_auth.admin_user manually."
        )

    if existing_user_ids:
        params["existing_user_id"] = next(iter(existing_user_ids))
        session.execute(
            text(
                "UPDATE app_auth.admin_user"
                " SET supabase_user_id = CAST(:user_id AS uuid),"
                "     email = :email,"
                "     enabled = :enabled,"
                "     updated_at = NOW()"
                " WHERE supabase_user_id = CAST(:existing_user_id AS uuid)"
            ),
            params,
        )
    else:
        session.execute(
            text(
                "INSERT INTO app_auth.admin_user"
                " (supabase_user_id, email, enabled, updated_at)"
                " VALUES (CAST(:user_id AS uuid), :email, :enabled, NOW())"
            ),
            params,
        )
    session.commit()
    return str(auth_user.id)


def main() -> None:
    parser = argparse.ArgumentParser(description="Allowlist a Supabase Auth user as CaseSignal admin.")
    parser.add_argument("--email", required=True, help="Supabase Auth user email to allowlist.")
    parser.add_argument(
        "--disabled",
        action="store_true",
        help="Insert or update the user as disabled.",
    )
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL must be set.")

    engine = create_engine(database_url)
    try:
        with Session(engine) as session:
            user_id = allowlist_admin_user(session, email=args.email, enabled=not args.disabled)
        print(f"Allowlisted Supabase admin user {user_id} for {args.email.strip().lower()}")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
