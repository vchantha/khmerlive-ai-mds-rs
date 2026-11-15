"""Durable public HTTP(S) stream source metadata.

Revision ID: 0004_stream_url
Revises: 0003_job_cancel
"""
from alembic import op
import sqlalchemy as sa
revision = "0004_stream_url"
down_revision = "0003_job_cancel"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("media_assets", sa.Column("source_url", sa.Text(), nullable=True))
    op.add_column("media_assets", sa.Column("source_kind", sa.String(16), nullable=False, server_default="upload"))
    op.add_column("media_assets", sa.Column("capture_seconds", sa.Integer(), nullable=True))

def downgrade():
    op.drop_column("media_assets", "capture_seconds")
    op.drop_column("media_assets", "source_kind")
    op.drop_column("media_assets", "source_url")
