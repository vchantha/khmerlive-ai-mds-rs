"""Translation glossary (required terminology)."""
from alembic import op
import sqlalchemy as sa
revision="0011_glossary"
down_revision="0010_translation_corrections"
branch_labels=None
depends_on=None

def upgrade():
    op.create_table("glossary_terms",
        sa.Column("id",sa.Integer(),primary_key=True,autoincrement=True),
        sa.Column("source_lang",sa.String(2),nullable=False),
        sa.Column("target_lang",sa.String(2),nullable=False),
        sa.Column("source_term",sa.String(200),nullable=False),
        sa.Column("target_term",sa.String(200),nullable=False),
        sa.Column("note",sa.String(500),nullable=True),
        sa.Column("created_by",sa.String(200),nullable=True),
        sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),
        sa.UniqueConstraint("source_lang","target_lang","source_term",name="uq_glossary_term"))

def downgrade():
    op.drop_table("glossary_terms")
