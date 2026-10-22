"""pg_trgm extension + GIN indexes for free-text search on names + IDs."""
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_cases_case_name_trgm "
        "ON cold_case.cases USING gin (case_name gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_cases_source_case_id_trgm "
        "ON cold_case.cases USING gin (source_case_id gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_victim_first_name_trgm "
        "ON cold_case.victim USING gin (first_name gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_victim_last_name_trgm "
        "ON cold_case.victim USING gin (last_name gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS cold_case.idx_victim_last_name_trgm")
    op.execute("DROP INDEX IF EXISTS cold_case.idx_victim_first_name_trgm")
    op.execute("DROP INDEX IF EXISTS cold_case.idx_cases_source_case_id_trgm")
    op.execute("DROP INDEX IF EXISTS cold_case.idx_cases_case_name_trgm")
    # Don't drop the extension — other features may rely on it later.
