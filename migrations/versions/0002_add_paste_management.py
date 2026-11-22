"""Add management keys and optional paste metadata."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("pastes", sa.Column("management_key_hash", sa.String(64), nullable=True))
    op.add_column("pastes", sa.Column("title", sa.String(200), nullable=True))
    op.add_column("pastes", sa.Column("language", sa.String(50), nullable=True))


def downgrade() -> None:
    op.drop_column("pastes", "language")
    op.drop_column("pastes", "title")
    op.drop_column("pastes", "management_key_hash")
