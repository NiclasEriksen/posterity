"""Deleted video

Revision ID: 38cda3a81b3e
Revises: b2af0d206d30
Create Date: 2022-04-17 19:05:28.156570

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '38cda3a81b3e'
down_revision = 'b2af0d206d30'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('deleted_videos',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('video_id', sa.String(), nullable=True),
    sa.Column('url', sa.String(), nullable=True),
    sa.Column('upload_time', sa.DateTime(), nullable=True),
    sa.Column('delete_time', sa.DateTime(), nullable=True),
    sa.Column('deleted_by', sa.String(), nullable=True),
    sa.Column('title', sa.String(), nullable=True),
    sa.Column('orig_title', sa.String(), nullable=True),
    sa.Column('source', sa.String(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('video_id')
    )
    op.create_table('category_deleted_association',
    sa.Column('video_id', sa.Integer(), nullable=True),
    sa.Column('category_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['category_id'], ['categories.id'], ),
    sa.ForeignKeyConstraint(['video_id'], ['deleted_videos.id'], )
    )
    op.create_table('tag_deleted_association',
    sa.Column('video_id', sa.Integer(), nullable=True),
    sa.Column('tag_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['tag_id'], ['content_tags.id'], ),
    sa.ForeignKeyConstraint(['video_id'], ['deleted_videos.id'], )
    )
    with op.batch_alter_table('categories', schema=None) as batch_op:
        batch_op.alter_column('stub',
               existing_type=sa.VARCHAR(length=50),
               nullable=True)

    with op.batch_alter_table('content_tags', schema=None) as batch_op:
        batch_op.alter_column('stub',
               existing_type=sa.VARCHAR(length=50),
               nullable=True)

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('content_tags', schema=None) as batch_op:
        batch_op.alter_column('stub',
               existing_type=sa.VARCHAR(length=50),
               nullable=False)

    with op.batch_alter_table('categories', schema=None) as batch_op:
        batch_op.alter_column('stub',
               existing_type=sa.VARCHAR(length=50),
               nullable=False)

    op.drop_table('tag_deleted_association')
    op.drop_table('category_deleted_association')
    op.drop_table('deleted_videos')
    # ### end Alembic commands ###
