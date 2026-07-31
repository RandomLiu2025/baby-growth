"""Current application schema baseline."""

from alembic import op
import sqlalchemy as sa


revision = "20260730_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("role", sa.String()),
        sa.Column("disabled", sa.Boolean()),
        sa.Column("createdAt", sa.String()),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)
    op.create_table(
        "invites",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String()),
        sa.Column("note", sa.String()),
        sa.Column("usedBy", sa.String()),
        sa.Column("usedAt", sa.String()),
        sa.Column("createdAt", sa.String()),
    )
    op.create_index("ix_invites_code", "invites", ["code"], unique=True)
    op.create_table(
        "baby",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String()),
        sa.Column("gender", sa.String()),
        sa.Column("birthday", sa.String()),
        sa.Column("avatar", sa.Text()),
        sa.Column("bio", sa.Text()),
        sa.Column("family", sa.Text()),
    )
    op.create_table(
        "milestones",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("date", sa.String()),
        sa.Column("title", sa.String()),
        sa.Column("category", sa.String()),
        sa.Column("desc", sa.Text()),
        sa.Column("image", sa.Text()),
        sa.Column("createdAt", sa.String()),
    )
    op.create_index("ix_milestones_date", "milestones", ["date"])
    op.create_table(
        "albums",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String()),
        sa.Column("date", sa.String()),
        sa.Column("desc", sa.Text()),
        sa.Column("cover", sa.Text()),
        sa.Column("createdAt", sa.String()),
    )
    op.create_table(
        "photos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("albumId", sa.Integer(), sa.ForeignKey("albums.id", ondelete="CASCADE")),
        sa.Column("url", sa.Text()),
        sa.Column("caption", sa.String()),
        sa.Column("desc", sa.Text()),
        sa.Column("takenAt", sa.String()),
        sa.Column("sort", sa.Integer()),
    )
    op.create_index("ix_photos_albumId", "photos", ["albumId"])
    op.create_table(
        "growth",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("date", sa.String()),
        sa.Column("height", sa.Float()),
        sa.Column("weight", sa.Float()),
        sa.Column("head", sa.Float()),
    )
    op.create_index("ix_growth_date", "growth", ["date"])
    op.create_table(
        "daily",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("type", sa.String()),
        sa.Column("feedType", sa.String()),
        sa.Column("amount", sa.Integer()),
        sa.Column("diaperType", sa.String()),
        sa.Column("time", sa.String()),
        sa.Column("note", sa.Text()),
    )
    op.create_index("ix_daily_time", "daily", ["time"])
    op.create_table(
        "diary",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("date", sa.String()),
        sa.Column("title", sa.String()),
        sa.Column("content", sa.Text()),
        sa.Column("images", sa.JSON()),
    )
    op.create_index("ix_diary_date", "diary", ["date"])
    op.create_table(
        "videos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("date", sa.String()),
        sa.Column("title", sa.String()),
        sa.Column("desc", sa.Text()),
        sa.Column("url", sa.Text()),
        sa.Column("cover", sa.Text()),
        sa.Column("createdAt", sa.String()),
    )
    op.create_index("ix_videos_date", "videos", ["date"])
    op.create_table(
        "vaccines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String()),
        sa.Column("dose", sa.Integer()),
        sa.Column("plannedMonth", sa.Integer()),
        sa.Column("date", sa.String()),
        sa.Column("note", sa.String()),
    )
    op.create_table(
        "shares",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("token", sa.String()),
        sa.Column("albumId", sa.Integer()),
        sa.Column("expiresAt", sa.String()),
        sa.Column("createdAt", sa.String()),
    )
    op.create_index("ix_shares_token", "shares", ["token"], unique=True)
    op.create_index("ix_shares_albumId", "shares", ["albumId"])
    op.create_table(
        "recaps",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("period", sa.String()),
        sa.Column("title", sa.String()),
        sa.Column("content", sa.Text()),
        sa.Column("createdAt", sa.String()),
    )
    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String()),
        sa.Column("content", sa.Text()),
        sa.Column("color", sa.String()),
        sa.Column("status", sa.String()),
        sa.Column("createdAt", sa.String()),
    )
    op.create_index("ix_messages_status", "messages", ["status"])
    op.create_table(
        "settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("data", sa.JSON()),
    )


def downgrade():
    op.drop_table("settings")
    op.drop_index("ix_messages_status", table_name="messages")
    op.drop_table("messages")
    op.drop_table("recaps")
    op.drop_index("ix_shares_albumId", table_name="shares")
    op.drop_index("ix_shares_token", table_name="shares")
    op.drop_table("shares")
    op.drop_table("vaccines")
    op.drop_index("ix_videos_date", table_name="videos")
    op.drop_table("videos")
    op.drop_index("ix_diary_date", table_name="diary")
    op.drop_table("diary")
    op.drop_index("ix_daily_time", table_name="daily")
    op.drop_table("daily")
    op.drop_index("ix_growth_date", table_name="growth")
    op.drop_table("growth")
    op.drop_index("ix_photos_albumId", table_name="photos")
    op.drop_table("photos")
    op.drop_table("albums")
    op.drop_index("ix_milestones_date", table_name="milestones")
    op.drop_table("milestones")
    op.drop_table("baby")
    op.drop_index("ix_invites_code", table_name="invites")
    op.drop_table("invites")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_table("users")
