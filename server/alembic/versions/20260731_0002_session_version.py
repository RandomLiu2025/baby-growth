"""Add user session version for token revocation.

Revision ID: 20260731_0002
Revises: 20260730_0001
"""

from alembic import op
import sqlalchemy as sa


revision = "20260731_0002"
down_revision = "20260730_0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "users",
        sa.Column("sessionVersion", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade():
    op.drop_column("users", "sessionVersion")
