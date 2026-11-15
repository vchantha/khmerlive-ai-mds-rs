"""Track worker stage and real progress checkpoints."""
from alembic import op
import sqlalchemy as sa
revision="0002_job_progress"
down_revision="0001_initial"
branch_labels=None
depends_on=None

def upgrade():
    op.add_column("translation_jobs",sa.Column("progress",sa.Integer(),nullable=False,server_default="0"))
    op.add_column("translation_jobs",sa.Column("stage",sa.String(64),nullable=True))
    op.execute("UPDATE translation_jobs SET progress=100,stage='completed' WHERE status='completed'")

def downgrade():
    op.drop_column("translation_jobs","stage")
    op.drop_column("translation_jobs","progress")
