"""Drop legacy unsalted SHA-256 ``key_hash`` column.

The dual-read window in ``casesignal.api.dependencies.auth.require_api_key``
is removed in the same change; all keys now authenticate via HMAC-SHA256
(``key_hmac``). Pre-V0: no production keys exist, so the column is dropped
unconditionally rather than gated on a preflight rotation check.
"""
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE app_auth.api_keys DROP CONSTRAINT IF EXISTS api_keys_key_hash_key")
    op.execute("ALTER TABLE app_auth.api_keys DROP COLUMN IF EXISTS key_hash")


def downgrade() -> None:
    op.execute("ALTER TABLE app_auth.api_keys ADD COLUMN key_hash TEXT")
    op.execute(
        "ALTER TABLE app_auth.api_keys"
        " ADD CONSTRAINT api_keys_key_hash_key UNIQUE (key_hash)"
    )
