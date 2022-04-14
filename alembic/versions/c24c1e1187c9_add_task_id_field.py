"""Add task id field

Revision ID: c24c1e1187c9
Revises: 70b28382f426
Create Date: 2022-04-14 19:12:10.511243

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c24c1e1187c9'
down_revision = '70b28382f426'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('videos', schema=None) as batch_op:
        batch_op.add_column(sa.Column('pid', sa.Integer(), nullable=True))

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('videos', schema=None) as batch_op:
        batch_op.drop_column('pid')

    # ### end Alembic commands ###
