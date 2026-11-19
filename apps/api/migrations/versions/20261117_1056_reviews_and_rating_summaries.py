"""Reviews and rating summaries (blueprint D.15, C-18, S-16, AD-12; D-066).

`reviews` (in the schema since 0001, unused until now) gains a `held`
state for reviews a pattern check flags for staff, the moderation record,
and length limits on the text and the seller's reply. `rating_summaries`
holds the derived rating totals per product and per seller.

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-17 10:56:37.554635+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = '0010'
down_revision: str | None = '0009'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('rating_summaries',
    sa.Column('subject_type', sa.Text(), nullable=False),
    sa.Column('subject_id', sa.UUID(), nullable=False),
    sa.Column('review_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('rating_sum', sa.Integer(), server_default='0', nullable=False),
    sa.Column('count_1', sa.Integer(), server_default='0', nullable=False),
    sa.Column('count_2', sa.Integer(), server_default='0', nullable=False),
    sa.Column('count_3', sa.Integer(), server_default='0', nullable=False),
    sa.Column('count_4', sa.Integer(), server_default='0', nullable=False),
    sa.Column('count_5', sa.Integer(), server_default='0', nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("subject_type in ('product', 'seller')", name=op.f('ck_rating_summaries_subject_type_allowed')),
    sa.CheckConstraint('count_1 + count_2 + count_3 + count_4 + count_5 = review_count', name=op.f('ck_rating_summaries_counts_add_up')),
    sa.CheckConstraint('count_1 >= 0 and count_2 >= 0 and count_3 >= 0 and count_4 >= 0 and count_5 >= 0', name=op.f('ck_rating_summaries_counts_non_negative')),
    sa.CheckConstraint('rating_sum between review_count and 5 * review_count', name=op.f('ck_rating_summaries_rating_sum_range')),
    sa.CheckConstraint('review_count >= 0', name=op.f('ck_rating_summaries_review_count_non_negative')),
    sa.PrimaryKeyConstraint('subject_type', 'subject_id', name=op.f('pk_rating_summaries'))
    )
    op.add_column('reviews', sa.Column('held_reason', sa.Text(), nullable=True))
    op.add_column('reviews', sa.Column('moderation_reason', sa.Text(), nullable=True))
    op.add_column('reviews', sa.Column('moderated_by_user_id', sa.UUID(), nullable=True))
    op.add_column('reviews', sa.Column('moderated_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index('ix_reviews_buyer_created', 'reviews', ['buyer_user_id', 'created_at'], unique=False)
    op.create_index('ix_reviews_status_created', 'reviews', ['moderation_status', 'created_at'], unique=False)
    op.create_foreign_key(op.f('fk_reviews_moderated_by_user_id_users'), 'reviews', 'users', ['moderated_by_user_id'], ['id'], ondelete='RESTRICT')
    # Alembic does not compare CHECK constraints; these mirror the model.
    op.drop_constraint(op.f('ck_reviews_moderation_status_allowed'), 'reviews', type_='check')
    op.create_check_constraint(
        op.f('ck_reviews_moderation_status_allowed'), 'reviews',
        "moderation_status in ('published', 'held', 'hidden')",
    )
    op.create_check_constraint(op.f('ck_reviews_body_length'), 'reviews', "length(body) <= 2000")
    op.create_check_constraint(
        op.f('ck_reviews_reply_length'), 'reviews',
        "seller_reply is null or length(btrim(seller_reply)) between 1 and 1000",
    )
    op.create_check_constraint(
        op.f('ck_reviews_held_has_reason'), 'reviews',
        "moderation_status <> 'held' or held_reason is not null",
    )
    op.create_check_constraint(
        op.f('ck_reviews_hidden_has_reason'), 'reviews',
        "moderation_status <> 'hidden' or moderation_reason is not null",
    )


def downgrade() -> None:
    # Migrations are forward-only (blueprint F.3). A mistake is corrected by a
    # new migration, never by rolling the schema back.
    raise NotImplementedError("migrations are forward-only")
