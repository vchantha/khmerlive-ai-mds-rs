"""OAuth-backed user identities and ownership of private jobs/media."""
from alembic import op
import sqlalchemy as sa
revision="0006_user_social_auth"
down_revision="0005_real_subtitles"
branch_labels=None
depends_on=None

def upgrade():
    op.create_table("app_users",
        sa.Column("id",sa.String(36),primary_key=True),
        sa.Column("display_name",sa.String(200),nullable=False),
        sa.Column("email",sa.String(320),nullable=True),
        sa.Column("avatar_url",sa.String(1000),nullable=True),
        sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False))
    op.create_table("social_identities",
        sa.Column("id",sa.String(36),primary_key=True),
        sa.Column("user_id",sa.String(36),sa.ForeignKey("app_users.id",ondelete="CASCADE"),nullable=False),
        sa.Column("provider",sa.String(30),nullable=False),
        sa.Column("subject",sa.String(255),nullable=False),
        sa.Column("display_name",sa.String(200),nullable=True),
        sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),
        sa.UniqueConstraint("provider","subject",name="uq_social_provider_subject"),
        sa.UniqueConstraint("user_id","provider",name="uq_user_provider"))
    op.add_column("media_assets",sa.Column("owner_user_id",sa.String(36),sa.ForeignKey("app_users.id"),nullable=True))
    op.add_column("translation_jobs",sa.Column("owner_user_id",sa.String(36),sa.ForeignKey("app_users.id"),nullable=True))
    op.create_index("ix_media_owner","media_assets",["owner_user_id"])
    op.create_index("ix_jobs_owner","translation_jobs",["owner_user_id"])

def downgrade():
    op.drop_index("ix_jobs_owner",table_name="translation_jobs")
    op.drop_index("ix_media_owner",table_name="media_assets")
    op.drop_column("translation_jobs","owner_user_id")
    op.drop_column("media_assets","owner_user_id")
    op.drop_table("social_identities")
    op.drop_table("app_users")
