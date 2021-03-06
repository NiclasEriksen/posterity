"""Duplicate field on deleted video

Revision ID: a5bd960ed142
Revises: de533c35c545
Create Date: 2022-04-19 22:15:18.651075

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a5bd960ed142'
down_revision = 'de533c35c545'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('deleted_videos', schema=None) as batch_op:
        batch_op.add_column(sa.Column('duplicate', sa.Boolean(), nullable=True))

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('deleted_videos', schema=None) as batch_op:
        batch_op.drop_column('duplicate')

    # ### end Alembic commands ###
