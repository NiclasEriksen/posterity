"""More fields to Videos

Revision ID: ae16be498531
Revises: 6015af7140fc
Create Date: 2022-03-19 18:23:30.473818

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'ae16be498531'
down_revision = '6015af7140fc'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('videos', sa.Column('safe_to_store', sa.Boolean(), nullable=True))
    op.add_column('videos', sa.Column('verified', sa.Boolean(), nullable=True))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('videos', 'verified')
    op.drop_column('videos', 'safe_to_store')
    # ### end Alembic commands ###
