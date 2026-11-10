"""initial_schema"""

import sqlalchemy as sa

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_user",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("login_id", sa.String(length=20), nullable=False),
        sa.Column("password", sa.String(length=60), nullable=False),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("login_id"),
    )
    op.create_table(
        "channel_cache",
        sa.Column("channel_id", sa.String(length=24), nullable=False),
        sa.Column("title", sa.String(length=100), nullable=False),
        sa.Column("thumbnail_url", sa.String(length=255), nullable=True),
        sa.Column("country", sa.String(length=2), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("subscriber_count", sa.BigInteger(), nullable=True),
        sa.Column(
            "hidden_subscriber", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column("video_count", sa.Integer(), nullable=True),
        sa.Column("view_count", sa.BigInteger(), nullable=True),
        sa.Column("uploads_playlist_id", sa.String(length=34), nullable=True),
        sa.Column("recent_uploads", sa.Text(), nullable=True),
        sa.Column("recent_fetched_at", sa.DateTime(), nullable=True),
        sa.Column(
            "fetched_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("channel_id"),
    )
    op.create_index(
        "ix_channel_cache_fetched_at", "channel_cache", ["fetched_at"], unique=False
    )
    op.create_table(
        "quota_usage",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("usage_date", sa.Date(), nullable=False),
        sa.Column("endpoint", sa.String(length=30), nullable=False),
        sa.Column("units", sa.Integer(), nullable=False),
        sa.Column("search_id", sa.CHAR(length=32), nullable=True),
        sa.Column(
            "called_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_quota_usage_usage_date", "quota_usage", ["usage_date"], unique=False
    )
    op.create_table(
        "search_cache",
        sa.Column("id", sa.CHAR(length=32), nullable=False),
        sa.Column("cond_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("conditions", sa.Text(), nullable=False),
        sa.Column("video_ids", sa.Text(), nullable=False),
        sa.Column("funnel", sa.Text(), nullable=False),
        sa.Column("warnings", sa.Text(), nullable=True),
        sa.Column("quota_spent", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_search_cache_cond_expires",
        "search_cache",
        ["cond_hash", "expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_search_cache_expires_at", "search_cache", ["expires_at"], unique=False
    )
    op.create_table(
        "video_cache",
        sa.Column("video_id", sa.String(length=11), nullable=False),
        sa.Column("channel_id", sa.String(length=24), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("thumbnail_url", sa.String(length=255), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=False),
        sa.Column("duration_sec", sa.Integer(), nullable=True),
        sa.Column("tags", sa.Text(), nullable=True),
        sa.Column("category_id", sa.Integer(), nullable=True),
        sa.Column("default_language", sa.String(length=10), nullable=True),
        sa.Column("definition", sa.String(length=2), nullable=True),
        sa.Column("made_for_kids", sa.Boolean(), nullable=True),
        sa.Column("region_allowed", sa.Text(), nullable=True),
        sa.Column("region_blocked", sa.Text(), nullable=True),
        sa.Column("view_count", sa.BigInteger(), nullable=True),
        sa.Column("like_count", sa.BigInteger(), nullable=True),
        sa.Column("comment_count", sa.BigInteger(), nullable=True),
        sa.Column(
            "fetched_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("video_id"),
    )
    op.create_index(
        "ix_video_cache_channel_id", "video_cache", ["channel_id"], unique=False
    )
    op.create_index(
        "ix_video_cache_fetched_at", "video_cache", ["fetched_at"], unique=False
    )
    op.create_table(
        "video_category_cache",
        sa.Column("region_code", sa.String(length=2), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=100), nullable=False),
        sa.Column("assignable", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("region_code", "category_id"),
    )
    op.create_table(
        "favorite_video",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("video_id", sa.String(length=11), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "video_id"),
    )
    op.create_index(
        "ix_favorite_video_user_created",
        "favorite_video",
        ["user_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "filter_preset",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=30), nullable=False),
        sa.Column("conditions", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "name"),
    )
    op.create_table(
        "search_history",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("keyword", sa.String(length=100), nullable=False),
        sa.Column("conditions", sa.Text(), nullable=False),
        sa.Column("result_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "searched_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_search_history_user_searched",
        "search_history",
        ["user_id", "searched_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_search_history_user_searched", table_name="search_history")
    op.drop_table("search_history")
    op.drop_table("filter_preset")
    op.drop_index("ix_favorite_video_user_created", table_name="favorite_video")
    op.drop_table("favorite_video")
    op.drop_table("video_category_cache")
    op.drop_index("ix_video_cache_fetched_at", table_name="video_cache")
    op.drop_index("ix_video_cache_channel_id", table_name="video_cache")
    op.drop_table("video_cache")
    op.drop_index("ix_search_cache_expires_at", table_name="search_cache")
    op.drop_index("ix_search_cache_cond_expires", table_name="search_cache")
    op.drop_table("search_cache")
    op.drop_index("ix_quota_usage_usage_date", table_name="quota_usage")
    op.drop_table("quota_usage")
    op.drop_index("ix_channel_cache_fetched_at", table_name="channel_cache")
    op.drop_table("channel_cache")
    op.drop_table("app_user")
