"""Product pictures and problem photos (blueprint F.6, P5, C-16; D-062).

`product_images` (in the schema since 0001, unused until now) gains its
pipeline state: a picture is uploaded, cleaned and kept privately as
`source_key`, then the worker renders it to WebP in two sizes and marks it
`ready`. Staff may remove one with a reason; nothing is deleted.

`problem_photos` holds the evidence photos a buyer or seller adds to a
reported problem. Evidence is never edited: like the history tables of 0002,
the application role loses UPDATE, DELETE and TRUNCATE on it, and a trigger
refuses UPDATE and DELETE for every role.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-17 09:36:11.229213+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "problem_photos",
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("author_type", sa.Text(), nullable=False),
        sa.Column("uploaded_by_user_id", sa.UUID(), nullable=False),
        sa.Column("file_key", sa.Text(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "author_type in ('buyer', 'seller')", name=op.f("ck_problem_photos_author_type_allowed")
        ),
        sa.CheckConstraint("size_bytes > 0", name=op.f("ck_problem_photos_size_positive")),
        sa.CheckConstraint(
            "width > 0 and height > 0", name=op.f("ck_problem_photos_dimensions_positive")
        ),
        sa.ForeignKeyConstraint(
            ["case_id"], ["dispute_cases.id"],
            name=op.f("fk_problem_photos_case_id_dispute_cases"), ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_user_id"], ["users.id"],
            name=op.f("fk_problem_photos_uploaded_by_user_id_users"), ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_problem_photos")),
        sa.UniqueConstraint("file_key", name=op.f("uq_problem_photos_file_key")),
    )
    op.create_index(
        "ix_problem_photos_case_created", "problem_photos", ["case_id", "created_at"], unique=False
    )
    op.execute(
        """
        create trigger trg_problem_photos_append_only
        before update or delete on problem_photos
        for each row execute function markx_forbid_change()
        """
    )
    op.execute("revoke update, delete, truncate on problem_photos from markx_app")

    op.add_column(
        "product_images",
        sa.Column("status", sa.Text(), server_default="processing", nullable=False),
    )
    op.add_column("product_images", sa.Column("source_key", sa.Text(), nullable=True))
    op.add_column("product_images", sa.Column("uploaded_by_user_id", sa.UUID(), nullable=True))
    op.add_column("product_images", sa.Column("thumb_bytes", sa.Integer(), nullable=True))
    op.add_column("product_images", sa.Column("main_bytes", sa.Integer(), nullable=True))
    op.add_column(
        "product_images", sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("product_images", sa.Column("failure_reason", sa.Text(), nullable=True))
    op.add_column(
        "product_images", sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("product_images", sa.Column("removed_reason", sa.Text(), nullable=True))
    op.add_column("product_images", sa.Column("removed_by_user_id", sa.UUID(), nullable=True))
    op.create_unique_constraint(
        op.f("uq_product_images_source_key"), "product_images", ["source_key"]
    )
    op.create_foreign_key(
        op.f("fk_product_images_removed_by_user_id_users"), "product_images", "users",
        ["removed_by_user_id"], ["id"], ondelete="RESTRICT",
    )
    op.create_foreign_key(
        op.f("fk_product_images_uploaded_by_user_id_users"), "product_images", "users",
        ["uploaded_by_user_id"], ["id"], ondelete="RESTRICT",
    )
    # Alembic does not compare CHECK constraints; these mirror the model.
    op.create_check_constraint(
        op.f("ck_product_images_status_allowed"), "product_images",
        "status in ('processing', 'ready', 'failed', 'removed')",
    )
    op.create_check_constraint(
        op.f("ck_product_images_ready_has_renditions"), "product_images",
        "status <> 'ready' or (processed_at is not null and thumb_bytes > 0 and main_bytes > 0)",
    )
    op.create_check_constraint(
        op.f("ck_product_images_removed_has_reason"), "product_images",
        "(status = 'removed') = (removed_at is not null and removed_reason is not null)",
    )


def downgrade() -> None:
    # Migrations are forward-only (blueprint F.3). A mistake is corrected by a
    # new migration, never by rolling the schema back.
    raise NotImplementedError("migrations are forward-only")
