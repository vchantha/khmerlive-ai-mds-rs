"""Persist subtitle artifacts and per-job processing mode.

Revision ID: 0005_real_subtitles
Revises: 0004_stream_url
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_real_subtitles"
down_revision = "0004_stream_url"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("translation_jobs", sa.Column("processing_mode", sa.String(32), nullable=False, server_default="demo"))
    op.add_column("translation_jobs", sa.Column("subtitle_key", sa.String(500), nullable=True))

def downgrade():
    op.drop_column("translation_jobs", "subtitle_key")
    op.drop_column("translation_jobs", "processing_mode")
