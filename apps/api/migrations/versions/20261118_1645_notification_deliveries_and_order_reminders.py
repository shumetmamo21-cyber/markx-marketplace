"""Notification delivery records and once-only order reminders (D-092).

`notification_deliveries` holds one row per notification and outside channel
(Telegram, SMS): whether it was accepted, failed, left unknown, skipped or
unavailable, and why. Never the text, a phone number or a Telegram id.

`seller_order_reminders` records a reminder already sent about a seller
order; its primary key makes "once" a database rule.

Two new tables only: nothing existing is changed, and no row is touched.

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-18 16:45:12.919064+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0016'
down_revision: str | None = '0015'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('notification_deliveries',
    sa.Column('notification_id', sa.UUID(), nullable=False),
    sa.Column('channel', sa.Text(), nullable=False),
    sa.Column('template', sa.Text(), nullable=False),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('provider', sa.Text(), nullable=True),
    sa.Column('provider_message_id', sa.Text(), nullable=True),
    sa.Column('sms_message_id', sa.UUID(), nullable=True),
    sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.CheckConstraint("channel in ('telegram', 'sms')", name=op.f('ck_notification_deliveries_channel_allowed')),
    sa.CheckConstraint("status in ('sending', 'retrying', 'accepted', 'failed', 'unknown', 'skipped', 'unavailable')", name=op.f('ck_notification_deliveries_status_allowed')),
    sa.CheckConstraint("status not in ('failed', 'unknown', 'skipped', 'unavailable', 'retrying') or reason is not null", name=op.f('ck_notification_deliveries_outcome_has_a_reason')),
    sa.CheckConstraint('attempts >= 0', name=op.f('ck_notification_deliveries_attempts_non_negative')),
    sa.CheckConstraint('provider_message_id is null or length(provider_message_id) between 1 and 128', name=op.f('ck_notification_deliveries_provider_message_id_length')),
    sa.CheckConstraint('reason is null or length(reason) <= 64', name=op.f('ck_notification_deliveries_reason_length')),
    sa.ForeignKeyConstraint(['notification_id'], ['notifications.id'], name=op.f('fk_notification_deliveries_notification_id_notifications'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_notification_deliveries')),
    sa.UniqueConstraint('notification_id', 'channel', name=op.f('uq_notification_deliveries_notification_id_channel'))
    )
    op.create_index('ix_notification_deliveries_open', 'notification_deliveries', ['updated_at'], unique=False, postgresql_where=sa.text("status in ('sending', 'retrying')"))
    op.create_index('ix_notification_deliveries_updated', 'notification_deliveries', ['updated_at'], unique=False)
    op.create_table('seller_order_reminders',
    sa.Column('seller_order_id', sa.UUID(), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('sent_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("kind in ('response_deadline')", name=op.f('ck_seller_order_reminders_kind_allowed')),
    sa.ForeignKeyConstraint(['seller_order_id'], ['seller_orders.id'], name=op.f('fk_seller_order_reminders_seller_order_id_seller_orders'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('seller_order_id', 'kind', name=op.f('pk_seller_order_reminders'))
    )


def downgrade() -> None:
    # Migrations are forward-only (blueprint F.3). A mistake is corrected by a
    # new migration, never by rolling the schema back.
    raise NotImplementedError("migrations are forward-only")
