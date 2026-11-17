"""Per-job subtitle segments and human translation corrections (fine-tuning data)."""
from alembic import op
import sqlalchemy as sa
revision="0010_translation_corrections"
down_revision="0009_job_events"
branch_labels=None
depends_on=None

def upgrade():
    op.add_column("translation_jobs",sa.Column("segments",sa.Text(),nullable=True))
    op.create_table("translation_corrections",
        sa.Column("id",sa.Integer(),primary_key=True,autoincrement=True),
        sa.Column("job_id",sa.String(36),sa.ForeignKey("translation_jobs.id",ondelete="CASCADE"),nullable=False),
        sa.Column("segment_index",sa.Integer(),nullable=False),
        sa.Column("start_ms",sa.Integer(),nullable=False),
        sa.Column("end_ms",sa.Integer(),nullable=False),
        sa.Column("source_lang",sa.String(2),nullable=False),
        sa.Column("target_lang",sa.String(2),nullable=False),
        sa.Column("source_text",sa.Text(),nullable=False),
        sa.Column("machine_text",sa.Text(),nullable=True),
        sa.Column("llm_text",sa.Text(),nullable=True),
        sa.Column("corrected_text",sa.Text(),nullable=False),
        sa.Column("approved_unchanged",sa.Boolean(),nullable=False,server_default=sa.false()),
        sa.Column("created_by",sa.String(200),nullable=True),
        sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),
        sa.Column("updated_at",sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),
        sa.UniqueConstraint("job_id","segment_index",name="uq_correction_job_segment"))
    op.create_index("ix_translation_corrections_job_id","translation_corrections",["job_id"])

def downgrade():
    op.drop_index("ix_translation_corrections_job_id",table_name="translation_corrections")
    op.drop_table("translation_corrections")
    op.drop_column("translation_jobs","segments")
