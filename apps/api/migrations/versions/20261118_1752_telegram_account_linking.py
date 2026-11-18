"""Connecting a person's Telegram account with a one-time link (D-093).

`telegram_link_tokens` holds each connection link: a keyed hash of its
token (never the token), the account and sign-in session it belongs to, its
expiry and how it ended. A partial unique index allows one pending link per
account. `telegram_updates` remembers the Telegram update ids the webhook has
handled, so a repeated delivery does nothing; it holds no message, sender or
chat.

`users.telegram_linked_at` records when the Telegram account was connected
and `users.telegram_unlinked_at` when it was last disconnected.
Accounts already linked (through the Mini App) get their last update time,
the best moment known; a constraint keeps it set exactly when a Telegram id
is. No other existing row is touched.

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-18 17:52:22.497898+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0017'
down_revision: str | None = '0016'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('telegram_updates',
    sa.Column('update_id', sa.BigInteger(), autoincrement=False, nullable=False),
    sa.Column('received_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('update_id', name=op.f('pk_telegram_updates'))
    )
    op.create_table('telegram_link_tokens',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('session_id', sa.UUID(), nullable=False),
    sa.Column('token_hash', sa.LargeBinary(), nullable=False),
    sa.Column('status', sa.Text(), server_default='pending', nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('failure_reason', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(status = 'failed') = (failure_reason is not null)", name=op.f('ck_telegram_link_tokens_failure_has_a_reason')),
    sa.CheckConstraint("(status = 'pending') = (finished_at is null)", name=op.f('ck_telegram_link_tokens_finished_unless_pending')),
    sa.CheckConstraint("failure_reason is null or failure_reason in ('telegram_in_use', 'already_connected', 'account_inactive', 'session_ended')", name=op.f('ck_telegram_link_tokens_failure_reason_allowed')),
    sa.CheckConstraint("status in ('pending', 'consumed', 'failed', 'revoked')", name=op.f('ck_telegram_link_tokens_status_allowed')),
    sa.CheckConstraint('expires_at > created_at', name=op.f('ck_telegram_link_tokens_expires_after_creation')),
    sa.CheckConstraint('octet_length(token_hash) = 32', name=op.f('ck_telegram_link_tokens_token_hash_length')),
    sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], name=op.f('fk_telegram_link_tokens_session_id_sessions'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_telegram_link_tokens_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_telegram_link_tokens')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_telegram_link_tokens_token_hash'))
    )
    op.create_index('ix_telegram_link_tokens_user_created', 'telegram_link_tokens', ['user_id', 'created_at'], unique=False)
    op.create_index('uq_telegram_link_tokens_one_pending_per_user', 'telegram_link_tokens', ['user_id'], unique=True, postgresql_where=sa.text("status = 'pending'"))
    op.add_column('users', sa.Column('telegram_linked_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('telegram_unlinked_at', sa.DateTime(timezone=True), nullable=True))
    op.execute(
        "update users set telegram_linked_at = updated_at "
        "where telegram_id is not null and telegram_linked_at is null"
    )
    op.create_check_constraint(
        op.f('ck_users_telegram_linked_at_with_telegram_id'),
        'users',
        '(telegram_id is null) = (telegram_linked_at is null)',
    )


def downgrade() -> None:
    # Migrations are forward-only (blueprint F.3). A mistake is corrected by a
    # new migration, never by rolling the schema back.
    raise NotImplementedError("migrations are forward-only")
