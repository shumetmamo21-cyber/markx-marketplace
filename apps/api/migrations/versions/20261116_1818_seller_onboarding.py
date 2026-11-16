"""Seller onboarding (blueprint P6).

* `seller_invitations`: onboarding is invite-only at launch (D.3).
* `sellers.review_state` gains `draft`: an application is filled in over
  several steps and reaches the staff queue only when it is submitted.
* `sellers.submitted_at`, `sellers.shop_visited_at`, `seller_documents.review_note`.
* Two CHECKs make staff approval a database fact: a seller can be `active` or
  `suspended`, or hold a verification level above 0, only when its
  application is `approved`.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-16 18:18:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = '0004'
down_revision: str | None = '0003'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('seller_invitations',
    sa.Column('phone', sa.Text(), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('invited_by_user_id', sa.UUID(), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('used_by_seller_id', sa.UUID(), nullable=True),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("phone ~ '^\\+251[79][0-9]{8}$'", name=op.f('ck_seller_invitations_phone_format')),
    sa.CheckConstraint('(used_at is null) = (used_by_seller_id is null)', name=op.f('ck_seller_invitations_used_fields_together')),
    sa.CheckConstraint('used_at is null or revoked_at is null', name=op.f('ck_seller_invitations_used_or_revoked_not_both')),
    sa.ForeignKeyConstraint(['invited_by_user_id'], ['users.id'], name=op.f('fk_seller_invitations_invited_by_user_id_users'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['used_by_seller_id'], ['sellers.id'], name=op.f('fk_seller_invitations_used_by_seller_id_sellers'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_seller_invitations'))
    )
    op.create_index('uq_seller_invitations_open_phone', 'seller_invitations', ['phone'], unique=True, postgresql_where=sa.text('used_at is null and revoked_at is null'))
    op.add_column('seller_documents', sa.Column('review_note', sa.Text(), nullable=True))
    op.add_column('sellers', sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('sellers', sa.Column('shop_visited_at', sa.DateTime(timezone=True), nullable=True))
    # Alembic does not detect changed CHECK constraints; these are written by hand.
    op.drop_constraint(op.f('ck_sellers_review_state_allowed'), 'sellers', type_='check')
    op.create_check_constraint(
        op.f('ck_sellers_review_state_allowed'), 'sellers',
        "review_state in ('draft', 'pending', 'needs_documents', 'approved', 'rejected')",
    )
    op.create_check_constraint(
        op.f('ck_sellers_trading_needs_approval'), 'sellers',
        "status not in ('active', 'suspended') or review_state = 'approved'",
    )
    op.create_check_constraint(
        op.f('ck_sellers_level_needs_approval'), 'sellers',
        "verification_level = 0 or review_state = 'approved'",
    )


def downgrade() -> None:
    # Migrations are forward-only (blueprint F.3). A mistake is corrected by a
    # new migration, never by rolling the schema back.
    raise NotImplementedError("migrations are forward-only")
