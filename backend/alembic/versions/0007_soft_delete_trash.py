"""Soft delete (Trash) for translation jobs and source videos."""
from alembic import op
import sqlalchemy as sa
revision="0007_soft_delete_trash"
down_revision="0006_user_social_auth"
branch_labels=None
depends_on=None

TABLES=("media_assets","translation_jobs")

def upgrade():
    for t in TABLES:
        op.add_column(t,sa.Column("deleted_at",sa.DateTime(timezone=True),nullable=True))
        op.add_column(t,sa.Column("deleted_by",sa.String(200),nullable=True))
        op.create_index(f"ix_{t}_deleted_at",t,["deleted_at"])

def downgrade():
    for t in TABLES:
        op.drop_index(f"ix_{t}_deleted_at",table_name=t)
        op.drop_column(t,"deleted_by")
        op.drop_column(t,"deleted_at")
