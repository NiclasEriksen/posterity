"""Duplicate id on deleted video

Revision ID: ee71de5ed9f4
Revises: ebfe7ffd7fba
Create Date: 2022-04-20 03:05:34.367498

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'ee71de5ed9f4'
down_revision = 'ebfe7ffd7fba'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('deleted_videos', schema=None) as batch_op:
        batch_op.add_column(sa.Column('duplicate_id', sa.String(), nullable=True))

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('deleted_videos', schema=None) as batch_op:
        batch_op.drop_column('duplicate_id')

    # ### end Alembic commands ###
