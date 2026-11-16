from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from markx.core.db import Base, CreatedAt, UUIDPrimaryKey, in_check
from markx.orders.models import DirectPaymentMethod
from markx.sellers.models import SellerPlan


class IntentStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    CANCELLED = "cancelled"


class RuleScope(StrEnum):
    DEFAULT = "default"
    CATEGORY = "category"
    PLAN = "plan"
    SELLER = "seller"


class AccountKind(StrEnum):
    ASSET = "asset"
    LIABILITY = "liability"
    INCOME = "income"
    EXPENSE = "expense"


class PaymentIntent(UUIDPrimaryKey, CreatedAt, Base):
    """What is due (blueprint G.2). One per seller order for direct payment.

    In Release 1 the only provider is "direct": the buyer pays the seller, and
    MarkX records the method and the time. MarkX never holds the money.
    """

    __tablename__ = "payment_intents"
    __table_args__ = (
        in_check("provider", ("direct",)),
        in_check("status", IntentStatus),
        in_check("method", DirectPaymentMethod),
        in_check("currency", ("ETB",)),
        CheckConstraint("amount_santim > 0", name="amount_positive"),
        CheckConstraint("(status = 'succeeded') = (settled_at is not null)", name="settled_has_time"),
        # One live intent per seller order: a seller order cannot be paid twice.
        Index(
            "uq_payment_intents_live_per_seller_order",
            "seller_order_id",
            unique=True,
            postgresql_where=text("status in ('pending', 'succeeded')"),
        ),
        Index("ix_payment_intents_order_id", "order_id"),
    )

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
    )
    seller_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("seller_orders.id", ondelete="RESTRICT"), nullable=False
    )
    # MarkX's own reference for this payment (blueprint J.4).
    reference: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False, server_default="direct")
    amount_santim: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False, server_default="ETB")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    method: Mapped[str | None] = mapped_column(Text)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PaymentAttempt(UUIDPrimaryKey, CreatedAt, Base):
    """Each try at paying. At most one success per intent (G.8 rule 2)."""

    __tablename__ = "payment_attempts"
    __table_args__ = (
        in_check("status", ("initiated", "pending", "succeeded", "failed", "expired")),
        Index(
            "uq_payment_attempts_one_success",
            "intent_id",
            unique=True,
            postgresql_where=text("status = 'succeeded'"),
        ),
    )

    intent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payment_intents.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(Text, nullable=False)
    provider_reference: Mapped[str | None] = mapped_column(Text)
    raw_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    recorded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class CommissionRule(UUIDPrimaryKey, CreatedAt, Base):
    """A fee rate. Versioned by date and never overwritten (blueprint D.19).

    The most specific rule in force when an order is placed wins: seller, then
    plan, then category, then default (J.8). Its rate is copied onto the line.
    """

    __tablename__ = "commission_rules"
    __table_args__ = (
        in_check("scope", RuleScope),
        in_check("payment_kind", ("direct", "protected")),
        in_check("plan", SellerPlan),
        CheckConstraint("rate_bps between 0 and 10000", name="rate_bps_range"),
        CheckConstraint("cap_santim is null or cap_santim >= 0", name="cap_non_negative"),
        CheckConstraint("valid_to is null or valid_to > valid_from", name="valid_range_ordered"),
        CheckConstraint(
            "(scope = 'category') = (category_id is not null)", name="category_scope_has_category"
        ),
        CheckConstraint(
            "(scope = 'seller') = (seller_id is not null)", name="seller_scope_has_seller"
        ),
        CheckConstraint("(scope = 'plan') = (plan is not null)", name="plan_scope_has_plan"),
        Index("ix_commission_rules_lookup", "payment_kind", "scope", "valid_from"),
    )

    scope: Mapped[str] = mapped_column(Text, nullable=False)
    payment_kind: Mapped[str] = mapped_column(Text, nullable=False)
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id", ondelete="RESTRICT")
    )
    seller_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sellers.id", ondelete="RESTRICT")
    )
    plan: Mapped[str | None] = mapped_column(Text)
    rate_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    cap_santim: Mapped[int | None] = mapped_column(BigInteger)
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class FeeCharge(UUIDPrimaryKey, CreatedAt, Base):
    """The fee on one seller order, charged when it completes (blueprint D.19)."""

    __tablename__ = "fee_charges"
    __table_args__ = (
        CheckConstraint("amount_santim >= 0", name="amount_non_negative"),
        CheckConstraint("item_value_santim > 0", name="item_value_positive"),
    )

    seller_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("seller_orders.id", ondelete="RESTRICT"),
        unique=True,
        nullable=False,
    )
    # The fee applies to item value, never to the delivery fee (J.8).
    item_value_santim: Mapped[int] = mapped_column(BigInteger, nullable=False)
    amount_santim: Mapped[int] = mapped_column(BigInteger, nullable=False)
    cap_applied: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    ledger_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ledger_transactions.id", ondelete="RESTRICT")
    )
    reversal_ledger_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ledger_transactions.id", ondelete="RESTRICT")
    )
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LedgerAccount(UUIDPrimaryKey, CreatedAt, Base):
    """The chart of accounts (blueprint G.2)."""

    __tablename__ = "ledger_accounts"
    __table_args__ = (in_check("kind", AccountKind),)

    code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    seller_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sellers.id", ondelete="RESTRICT")
    )


class LedgerTransaction(UUIDPrimaryKey, CreatedAt, Base):
    """One balanced set of ledger entries. Append-only (G.8 rule 5)."""

    __tablename__ = "ledger_transactions"

    idempotency_key: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    reference_type: Mapped[str] = mapped_column(Text, nullable=False)
    reference_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")


class LedgerEntry(UUIDPrimaryKey, CreatedAt, Base):
    """A debit or a credit. Debits equal credits in every transaction.

    The balance is enforced by a deferred constraint trigger, checked at commit.
    """

    __tablename__ = "ledger_entries"
    __table_args__ = (
        in_check("direction", ("debit", "credit")),
        in_check("currency", ("ETB",)),
        CheckConstraint("amount_santim > 0", name="amount_positive"),
        Index("ix_ledger_entries_transaction_id", "transaction_id"),
        Index("ix_ledger_entries_account_id", "account_id"),
    )

    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ledger_transactions.id", ondelete="RESTRICT"), nullable=False
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ledger_accounts.id", ondelete="RESTRICT"), nullable=False
    )
    direction: Mapped[str] = mapped_column(Text, nullable=False)
    amount_santim: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False, server_default="ETB")
