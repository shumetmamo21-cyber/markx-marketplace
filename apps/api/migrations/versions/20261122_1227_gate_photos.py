"""A photo of the buyer's gate on an address (C-08; D-107).

`gate_photos` holds the photos, private like `problem_photos`: re-encoded
to WebP without metadata at upload, kept in private storage, never edited
or deleted. Like the evidence photos of 0008, the application role loses
UPDATE, DELETE and TRUNCATE on it, and a trigger refuses UPDATE and DELETE
for every role.

`addresses.gate_photo_id` points at the address's current photo. The
foreign key is on (photo, owner), so an address can only ever hold a photo
its own buyer uploaded; the database refuses anyone else's. Each order
keeps the photo's id in its address snapshot, so changing or removing the
address's photo never alters what a past order shows.

Existing rows: every address starts with no photo.

Revision ID: 0023
Revises: 0022
Create Date: 2026-11-22 12:27:48.521630+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0023'
down_revision: str | None = '0022'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'gate_photos',
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('file_key', sa.Text(), nullable=False),
        sa.Column('width', sa.Integer(), nullable=False),
        sa.Column('height', sa.Integer(), nullable=False),
        sa.Column('size_bytes', sa.Integer(), nullable=False),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        sa.CheckConstraint(
            "file_key ~ '^gate-photos/'", name=op.f('ck_gate_photos_file_key_private_prefix')
        ),
        sa.CheckConstraint('size_bytes > 0', name=op.f('ck_gate_photos_size_positive')),
        sa.CheckConstraint(
            'width > 0 and height > 0', name=op.f('ck_gate_photos_dimensions_positive')
        ),
        sa.ForeignKeyConstraint(
            ['user_id'], ['users.id'], name=op.f('fk_gate_photos_user_id_users'),
            ondelete='RESTRICT',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_gate_photos')),
        sa.UniqueConstraint('file_key', name=op.f('uq_gate_photos_file_key')),
        sa.UniqueConstraint('id', 'user_id', name='uq_gate_photos_id_user_id'),
    )
    op.create_index('ix_gate_photos_user_id', 'gate_photos', ['user_id'], unique=False)
    op.execute(
        """
        create trigger trg_gate_photos_append_only
        before update or delete on gate_photos
        for each row execute function markx_forbid_change()
        """
    )
    op.execute("revoke update, delete, truncate on gate_photos from markx_app")

    op.add_column('addresses', sa.Column('gate_photo_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'fk_addresses_gate_photo_owner', 'addresses', 'gate_photos',
        ['gate_photo_id', 'user_id'], ['id', 'user_id'],
    )


def downgrade() -> None:
    # Migrations are forward-only (blueprint F.3). A mistake is corrected by a
    # new migration, never by rolling the schema back.
    raise NotImplementedError("migrations are forward-only")
