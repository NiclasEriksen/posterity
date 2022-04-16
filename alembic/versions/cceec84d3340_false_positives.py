"""False positives

Revision ID: cceec84d3340
Revises: 83dea6fa9a86
Create Date: 2022-04-15 23:16:21.996779

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'cceec84d3340'
down_revision = '83dea6fa9a86'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('reports', schema=None) as batch_op:
        batch_op.alter_column('source',
               existing_type=sa.VARCHAR(),
               nullable=True,
               existing_server_default=sa.text("''::character varying"))

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('reports', schema=None) as batch_op:
        batch_op.alter_column('source',
               existing_type=sa.VARCHAR(),
               nullable=False,
               existing_server_default=sa.text("''::character varying"))

    # ### end Alembic commands ###