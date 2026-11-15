"""Create media and translation job tables."""
from alembic import op
import sqlalchemy as sa
revision="0001_initial"
down_revision=None
branch_labels=None
depends_on=None

def upgrade():
    op.create_table("media_assets",
        sa.Column("id",sa.String(36),primary_key=True),
        sa.Column("filename",sa.String(255),nullable=False),
        sa.Column("object_key",sa.String(500),nullable=False,unique=True),
        sa.Column("content_type",sa.String(100),nullable=False),
        sa.Column("size_bytes",sa.BigInteger(),nullable=False),
        sa.Column("sha256",sa.String(64),nullable=False),
        sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False))
    op.create_table("translation_jobs",
        sa.Column("id",sa.String(36),primary_key=True),
        sa.Column("media_id",sa.String(36),sa.ForeignKey("media_assets.id"),nullable=False),
        sa.Column("source_lang",sa.String(2),nullable=False),
        sa.Column("target_lang",sa.String(2),nullable=False),
        sa.Column("status",sa.String(32),nullable=False,server_default="queued"),
        sa.Column("error",sa.Text(),nullable=True),
        sa.Column("transcript",sa.Text(),nullable=True),
        sa.Column("translation",sa.Text(),nullable=True),
        sa.Column("output_key",sa.String(500),nullable=True),
        sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),
        sa.Column("updated_at",sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False))
    op.create_index("ix_jobs_status_created","translation_jobs",["status","created_at"])

def downgrade():
    op.drop_index("ix_jobs_status_created",table_name="translation_jobs")
    op.drop_table("translation_jobs")
    op.drop_table("media_assets")
