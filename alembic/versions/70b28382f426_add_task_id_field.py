"""Add task id field

Revision ID: 70b28382f426
Revises: 03ecc716a68a
Create Date: 2022-04-14 15:52:26.413813

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '70b28382f426'
down_revision = '03ecc716a68a'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('videos', schema=None) as batch_op:
        batch_op.add_column(sa.Column('task_id', sa.String(), nullable=True))

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('videos', schema=None) as batch_op:
        batch_op.drop_column('task_id')

    # ### end Alembic commands ###
