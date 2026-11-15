"""Queue cancellation request field for real dashboard actions.

Revision ID: 0003_job_cancel
Revises: 0002_job_progress
"""
from alembic import op
import sqlalchemy as sa
revision = "0003_job_cancel"
down_revision = "0002_job_progress"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("translation_jobs", sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()))

def downgrade():
    op.drop_column("translation_jobs", "cancel_requested")
