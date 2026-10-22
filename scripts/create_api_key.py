#!/usr/bin/env python
"""
Create an API key and store its HMAC-SHA256 digest in app_auth.api_keys.

Usage:
    KEY_HMAC_SECRET=<secret> DATABASE_URL=postgresql+psycopg2://... \\
        python scripts/create_api_key.py "my-consumer-label" [--role reader|operator|admin]

    Role defaults to 'reader' if not specified.

Prints the key prefix (safe to log) and the full plaintext key (store now —
it will not be shown again). The plaintext is never stored.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac as _hmac
import os
import secrets
import sys

from sqlalchemy import create_engine, text


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an API key")
    parser.add_argument("label", help="Label for the API key")
    parser.add_argument(
        "--role",
        choices=["reader", "operator", "admin"],
        default="reader",
        help="Role for the API key (default: reader)",
    )
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL environment variable must be set.", file=sys.stderr)
        sys.exit(1)

    hmac_secret_str = os.environ.get("KEY_HMAC_SECRET", "")
    if not hmac_secret_str:
        print("KEY_HMAC_SECRET environment variable must be set.", file=sys.stderr)
        print(
            "Generate one with: python -c 'import secrets; print(secrets.token_hex(32))'",
            file=sys.stderr,
        )
        sys.exit(1)

    prefix_random = secrets.token_hex(4)   # 8 hex chars
    secret_random = secrets.token_hex(26)  # 52 hex chars
    plaintext_key = f"csk_{prefix_random}{secret_random}"  # "csk_" + 60 hex chars
    hmac_secret = hmac_secret_str.encode()
    digest = _hmac.new(hmac_secret, plaintext_key.encode(), hashlib.sha256).hexdigest()
    prefix_visible = plaintext_key[:12]  # "csk_" + 8 hex

    engine = create_engine(database_url)
    with engine.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO app_auth.api_keys (key_hmac, key_prefix, label, role)"
                " VALUES (:hmac, :prefix, :label, :role)"
            ),
            {"hmac": digest, "prefix": prefix_visible, "label": args.label, "role": args.role},
        )
        conn.commit()

    print(f"API key created for label '{args.label}' with role '{args.role}'.")
    print(f"Key prefix (safe to log): {prefix_visible}")
    print(f"Full key (store now, cannot be retrieved):\n{plaintext_key}")


if __name__ == "__main__":
    main()