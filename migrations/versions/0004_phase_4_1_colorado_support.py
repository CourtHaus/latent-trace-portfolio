"""Phase 4.1 — Colorado support: 9 new nullable columns.

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-11
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cases", sa.Column("namus_case_id", sa.Text(), nullable=True), schema="cold_case")
    op.add_column("cases", sa.Column("ncmec_case_id", sa.Text(), nullable=True), schema="cold_case")
    op.add_column("victim", sa.Column("dob", sa.Text(), nullable=True), schema="cold_case")
    op.add_column("victim", sa.Column("dod", sa.Text(), nullable=True), schema="cold_case")
    op.add_column("victim", sa.Column("ethnicity", sa.Text(), nullable=True), schema="cold_case")
    op.add_column("victim", sa.Column("tribal_affiliation", sa.Text(), nullable=True), schema="cold_case")
    op.add_column("victim", sa.Column("identifying_marks", sa.Text(), nullable=True), schema="cold_case")
    op.add_column("victim", sa.Column("aliases", sa.Text(), nullable=True), schema="cold_case")
    op.add_column("victim", sa.Column("occupation", sa.Text(), nullable=True), schema="cold_case")


def downgrade() -> None:
    for col in ("occupation", "aliases", "identifying_marks", "tribal_affiliation", "ethnicity", "dod", "dob"):
        op.drop_column("victim", col, schema="cold_case")
    for col in ("ncmec_case_id", "namus_case_id"):
        op.drop_column("cases", col, schema="cold_case")
