"""Mark designated seed clients with test public IDs.

Revision ID: 20260727_06
Revises: 20260727_05
"""

import sqlalchemy as sa
from alembic import op

revision = "20260727_06"
down_revision = "20260727_05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    for client_id in (2, 3):
        connection.execute(
            sa.text(
                "UPDATE clients SET client_code = :new_code "
                "WHERE id = :client_id AND client_code = :old_code"
            ),
            {
                "client_id": client_id,
                "old_code": f"client_{client_id:04d}",
                "new_code": f"test_{client_id:04d}",
            },
        )


def downgrade() -> None:
    connection = op.get_bind()
    for client_id in (2, 3):
        connection.execute(
            sa.text(
                "UPDATE clients SET client_code = :old_code "
                "WHERE id = :client_id AND client_code = :new_code"
            ),
            {
                "client_id": client_id,
                "old_code": f"client_{client_id:04d}",
                "new_code": f"test_{client_id:04d}",
            },
        )
