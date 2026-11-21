"""Signing in with Telegram on the website, and single-use Mini App data (D-101).

`telegram_sign_ins` holds each website sign-in through the bot: keyed hashes
of the link's token and of the browser's private secret (never either
value), the Telegram account that opened it, the account it signed in, its
expiry and how it ended. Constraints keep each state consistent.

`telegram_init_data_uses` remembers, by keyed hash, Mini App start-up data
already used to sign in, so the same data signs in once (audit finding M4).

New tables only: no existing row or column is touched.

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-21 09:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0020'
down_revision: str | None = '0019'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('telegram_init_data_uses',
    sa.Column('digest', sa.LargeBinary(), nullable=False),
    sa.Column('purpose', sa.Text(), nullable=False),
    sa.Column('used_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("purpose in ('sign_in')", name=op.f('ck_telegram_init_data_uses_purpose_allowed')),
    sa.CheckConstraint('octet_length(digest) = 32', name=op.f('ck_telegram_init_data_uses_digest_length')),
    sa.PrimaryKeyConstraint('digest', 'purpose', name=op.f('pk_telegram_init_data_uses'))
    )
    op.create_index('ix_telegram_init_data_uses_used_at', 'telegram_init_data_uses', ['used_at'], unique=False)
    op.create_table('telegram_sign_ins',
    sa.Column('token_hash', sa.LargeBinary(), nullable=False),
    sa.Column('browser_hash', sa.LargeBinary(), nullable=False),
    sa.Column('status', sa.Text(), server_default='pending', nullable=False),
    sa.Column('language', sa.Text(), server_default='am', nullable=False),
    sa.Column('telegram_id', sa.BigInteger(), nullable=True),
    sa.Column('user_id', sa.UUID(), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('opened_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('failure_reason', sa.Text(), nullable=True),
    sa.Column('ip', postgresql.INET(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(finished_at is null) = (status in ('pending', 'opened', 'confirmed'))", name=op.f('ck_telegram_sign_ins_finished_once_settled')),
    sa.CheckConstraint("(status = 'refused') = (failure_reason is not null)", name=op.f('ck_telegram_sign_ins_refusal_has_a_reason')),
    sa.CheckConstraint("(user_id is not null) = (status in ('confirmed', 'consumed'))", name=op.f('ck_telegram_sign_ins_account_once_confirmed')),
    sa.CheckConstraint("failure_reason is null or failure_reason in ('phone_not_ethiopian', 'phone_on_other_telegram', 'phone_in_use', 'account_inactive')", name=op.f('ck_telegram_sign_ins_failure_reason_allowed')),
    sa.CheckConstraint("language in ('am', 'en')", name=op.f('ck_telegram_sign_ins_language_allowed')),
    sa.CheckConstraint("status in ('pending', 'opened', 'confirmed', 'consumed', 'refused', 'revoked')", name=op.f('ck_telegram_sign_ins_status_allowed')),
    sa.CheckConstraint("status not in ('opened', 'confirmed', 'consumed') or telegram_id is not null", name=op.f('ck_telegram_sign_ins_opened_by_a_telegram_account')),
    sa.CheckConstraint('expires_at > created_at', name=op.f('ck_telegram_sign_ins_expires_after_creation')),
    sa.CheckConstraint('octet_length(browser_hash) = 32', name=op.f('ck_telegram_sign_ins_browser_hash_length')),
    sa.CheckConstraint('octet_length(token_hash) = 32', name=op.f('ck_telegram_sign_ins_token_hash_length')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_telegram_sign_ins_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_telegram_sign_ins')),
    sa.UniqueConstraint('browser_hash', name=op.f('uq_telegram_sign_ins_browser_hash')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_telegram_sign_ins_token_hash'))
    )
    op.create_index('ix_telegram_sign_ins_created_at', 'telegram_sign_ins', ['created_at'], unique=False)
    op.create_index('ix_telegram_sign_ins_telegram_status', 'telegram_sign_ins', ['telegram_id', 'status'], unique=False)


def downgrade() -> None:
    # Migrations are forward-only (blueprint F.3). A mistake is corrected by a
    # new migration, never by rolling the schema back.
    raise NotImplementedError("migrations are forward-only")
