"""Add photo taken date index for recap range queries.

Revision ID: 20260731_0003
Revises: 20260731_0002
"""

from alembic import op
import sqlalchemy as sa


revision = "20260731_0003"
down_revision = "20260731_0002"
branch_labels = None
depends_on = None


INDEX_NAME = "ix_photos_takenAt"


def _index_names():
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("photos")}


def upgrade():
    if INDEX_NAME not in _index_names():
        op.create_index(INDEX_NAME, "photos", ["takenAt"], unique=False)


def downgrade():
    if INDEX_NAME in _index_names():
        op.drop_index(INDEX_NAME, table_name="photos")
