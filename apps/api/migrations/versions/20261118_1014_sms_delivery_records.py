"""SMS delivery records (D-089).

`sms_messages` holds one row per SMS MarkX tries to send: its purpose, a
keyed hash of the number (never the number itself), the login-code challenge
or notification it belongs to, the provider, the provider's message id, the
status, a provider-independent error code, the number of segments and the
times. It never holds the message text or a code.

A new table only: nothing existing is changed, and no row is touched.

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-18 10:14:34.795906+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0015'
down_revision: str | None = '0014'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('sms_messages',
    sa.Column('purpose', sa.Text(), nullable=False),
    sa.Column('phone_ref', sa.LargeBinary(), nullable=False),
    sa.Column('otp_challenge_id', sa.UUID(), nullable=True),
    sa.Column('notification_id', sa.UUID(), nullable=True),
    sa.Column('provider', sa.Text(), nullable=False),
    sa.Column('provider_message_id', sa.Text(), nullable=True),
    sa.Column('status', sa.Text(), server_default='pending', nullable=False),
    sa.Column('error_code', sa.Text(), nullable=True),
    sa.Column('segments', sa.SmallInteger(), server_default='1', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.CheckConstraint("(purpose = 'login_code' and otp_challenge_id is not null and notification_id is null) or (purpose = 'notification' and notification_id is not null and otp_challenge_id is null)", name=op.f('ck_sms_messages_reference_matches_purpose')),
    sa.CheckConstraint("purpose in ('login_code', 'notification')", name=op.f('ck_sms_messages_purpose_allowed')),
    sa.CheckConstraint("status in ('pending', 'accepted', 'failed', 'unknown', 'delivered', 'undelivered')", name=op.f('ck_sms_messages_status_allowed')),
    sa.CheckConstraint("status not in ('failed', 'unknown', 'undelivered') or error_code is not null", name=op.f('ck_sms_messages_failure_has_an_error_code')),
    sa.CheckConstraint('error_code is null or length(error_code) <= 64', name=op.f('ck_sms_messages_error_code_length')),
    sa.CheckConstraint('octet_length(phone_ref) = 32', name=op.f('ck_sms_messages_phone_ref_is_a_keyed_hash')),
    sa.CheckConstraint('provider_message_id is null or length(provider_message_id) between 1 and 128', name=op.f('ck_sms_messages_provider_message_id_length')),
    sa.CheckConstraint('segments between 1 and 255', name=op.f('ck_sms_messages_segments_range')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sms_messages'))
    )
    op.create_index('ix_sms_messages_created', 'sms_messages', ['created_at'], unique=False)
    op.create_index('ix_sms_messages_phone_ref_created', 'sms_messages', ['phone_ref', 'created_at'], unique=False)
    op.create_index('ix_sms_messages_unfinished', 'sms_messages', ['created_at'], unique=False, postgresql_where=sa.text("status in ('pending', 'unknown')"))


def downgrade() -> None:
    # Migrations are forward-only (blueprint F.3). A mistake is corrected by a
    # new migration, never by rolling the schema back.
    raise NotImplementedError("migrations are forward-only")
