"""Per-job pipeline log and LLM task records."""
from alembic import op
import sqlalchemy as sa
revision="0009_job_events"
down_revision="0008_job_timings"
branch_labels=None
depends_on=None

def upgrade():
    op.create_table("job_events",
        sa.Column("id",sa.Integer(),primary_key=True,autoincrement=True),
        sa.Column("job_id",sa.String(36),sa.ForeignKey("translation_jobs.id",ondelete="CASCADE"),nullable=False),
        sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),
        sa.Column("stage",sa.String(40),nullable=False),
        sa.Column("level",sa.String(10),nullable=False,server_default="info"),
        sa.Column("message",sa.Text(),nullable=False),
        sa.Column("seconds",sa.Float(),nullable=True),
        sa.Column("data",sa.Text(),nullable=True))
    op.create_index("ix_job_events_job_id","job_events",["job_id"])

def downgrade():
    op.drop_index("ix_job_events_job_id",table_name="job_events")
    op.drop_table("job_events")
