"""Per-stage timing of translation jobs."""
from alembic import op
import sqlalchemy as sa
revision="0008_job_timings"
down_revision="0007_soft_delete_trash"
branch_labels=None
depends_on=None

def upgrade():
    op.add_column("translation_jobs",sa.Column("timings",sa.Text(),nullable=True))

def downgrade():
    op.drop_column("translation_jobs","timings")
