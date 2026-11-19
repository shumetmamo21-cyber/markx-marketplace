"""Copy the files of a local-disk installation into object storage (D-090).

MarkX on a laptop keeps its files in two folders under MARKX_STORAGE_DIR
(`private/` and `public/`). A server keeps them in two buckets. This tool
copies every file the database refers to from the folders into the buckets
configured by MARKX_FILE_STORAGE_PROVIDER and the MARKX_STORAGE_* settings,
under the same keys, so every row keeps pointing at its file.

    # 1. What would be copied, and what is missing or in the way. Writes nothing.
    uv run python -m scripts.copy_files_to_object_storage --from-dir ./var/storage

    # 2. Copy, then read every copy back and compare it with the original.
    uv run python -m scripts.copy_files_to_object_storage --from-dir ./var/storage \\
        --execute --founder-approved

It never deletes or changes a local file, never changes a database row and
never overwrites an object that is already in a bucket: an object with the
same key and different bytes is reported and left alone. It never runs by
itself. Sellers' identity documents are personal data: copying them to a
provider is the founder's decision (F-01), so `--execute` also needs
`--founder-approved`, given only once the founder has approved that copy in
writing. The output names rows by their database id, never by file key.

Exit status: 0 when every file is copied or already there, 1 when any file
is missing, in the way, refused or could not be copied, 2 for a usage error.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from markx import registry  # noqa: F401  (every model, for the queries below)
from markx.catalog.models import ProductImage
from markx.core.config import get_config
from markx.core.db import session_scope
from markx.core.storage import (
    LocalPrivateStorage,
    LocalPublicStorage,
    ObjectStore,
    StorageUnavailable,
    StoredFileMissing,
    StoredFileRefused,
    StoreName,
    get_private_storage,
    get_public_storage,
    sniff_image_type,
)
from markx.images.service import main_key, thumb_key
from markx.sellers.models import SellerDocument
from markx.trust.models import ProblemPhoto


@dataclass(frozen=True, slots=True)
class FileRef:
    """One file a database row refers to."""

    kind: str  # seller_document, picture_source, picture_thumb, picture_main, problem_photo
    row_id: uuid.UUID
    store: StoreName
    key: str
    content_type: str | None  # None: read from the bytes


def file_references(db: Session) -> list[FileRef]:
    """Every file the database refers to, in a stable order. Reads only."""
    refs: list[FileRef] = []
    for document in db.scalars(select(SellerDocument).order_by(SellerDocument.id)):
        refs.append(
            FileRef("seller_document", document.id, "private", document.file_key,
                    document.content_type)
        )  # fmt: skip
    for image in db.scalars(select(ProductImage).order_by(ProductImage.id)):
        if image.source_key is not None:
            refs.append(FileRef("picture_source", image.id, "private", image.source_key, None))
        # Rendered once; a picture removed later keeps its files (D-062).
        if image.processed_at is not None:
            refs.append(
                FileRef("picture_thumb", image.id, "public", thumb_key(image), "image/webp")
            )
            refs.append(FileRef("picture_main", image.id, "public", main_key(image), "image/webp"))
    for photo in db.scalars(select(ProblemPhoto).order_by(ProblemPhoto.id)):
        refs.append(FileRef("problem_photo", photo.id, "private", photo.file_key, "image/webp"))
    return refs


# Outcomes. The first three are fine; the rest make the exit status 1.
COPIED, WOULD_COPY, ALREADY_THERE = "copied", "would_copy", "already_there"
MISSING_LOCALLY, IN_THE_WAY, REFUSED, FAILED = "missing_locally", "in_the_way", "refused", "failed"
PROBLEMS = frozenset({MISSING_LOCALLY, IN_THE_WAY, REFUSED, FAILED})


@dataclass(frozen=True, slots=True)
class Outcome:
    ref: FileRef
    result: str
    reason: str = ""


def copy_files(
    refs: Iterable[FileRef],
    source: Mapping[StoreName, ObjectStore],
    target: Mapping[StoreName, ObjectStore],
    *,
    execute: bool,
) -> list[Outcome]:
    """Copy each referenced file from `source` to `target`, under its own key.

    Nothing is ever deleted, and nothing already in `target` is replaced.
    Without `execute`, only reads happen."""
    outcomes: list[Outcome] = []
    for ref in refs:
        outcomes.append(_copy_one(ref, source[ref.store], target[ref.store], execute=execute))
    return outcomes


def _copy_one(ref: FileRef, source: ObjectStore, target: ObjectStore, *, execute: bool) -> Outcome:
    try:
        data = source.get(ref.key)
    except StoredFileMissing:
        return Outcome(ref, MISSING_LOCALLY)
    except StoredFileRefused as exc:
        return Outcome(ref, REFUSED, str(exc))
    content_type = ref.content_type or sniff_image_type(data)
    if content_type is None or sniff_image_type(data) != content_type:
        return Outcome(ref, REFUSED, "the bytes are not the picture type the row says")
    try:
        if target.exists(ref.key):
            same = target.get(ref.key) == data
            return Outcome(ref, ALREADY_THERE if same else IN_THE_WAY)
        if not execute:
            return Outcome(ref, WOULD_COPY)
        target.put(ref.key, data, content_type)
        if target.get(ref.key) != data:
            return Outcome(ref, FAILED, "the copy read back differs from the original")
    except StoredFileRefused as exc:
        return Outcome(ref, REFUSED, str(exc))
    except StorageUnavailable as exc:
        return Outcome(ref, FAILED, exc.reason)
    return Outcome(ref, COPIED)


def report(outcomes: list[Outcome]) -> str:
    counts = Counter((o.ref.kind, o.result) for o in outcomes)
    lines = [f"{len(outcomes)} file(s) referred to by the database"]
    lines += [f"  {kind:16} {result:16} {n}" for (kind, result), n in sorted(counts.items())]
    problems = [o for o in outcomes if o.result in PROBLEMS]
    if problems:
        lines.append("Problems (by database row id; nothing was changed for these):")
        lines += [
            f"  {o.ref.kind} {o.ref.row_id}: {o.result}" + (f" ({o.reason})" if o.reason else "")
            for o in problems
        ]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.copy_files_to_object_storage",
        description="Copy MarkX's local files into the configured object storage. "
        "A dry run unless --execute is given; never deletes or overwrites anything.",
    )
    parser.add_argument("--from-dir", required=True, type=Path,
                        help="the MARKX_STORAGE_DIR of the installation the files come from")  # fmt: skip
    parser.add_argument("--execute", action="store_true", help="copy (default: only report)")
    parser.add_argument("--founder-approved", action="store_true",
                        help="the founder has approved, in writing, copying these files, "
                        "sellers' identity documents included, to this provider (F-01)")  # fmt: skip
    args = parser.parse_args(argv)

    config = get_config()
    if config.file_storage_provider == "local":
        parser.error("MARKX_FILE_STORAGE_PROVIDER names no object storage to copy into")
    if args.execute and not args.founder_approved:
        parser.error("--execute copies personal documents to a provider: it needs "
                     "--founder-approved, given only with the founder's written approval")  # fmt: skip
    root: Path = args.from_dir
    if not (root / "private").is_dir() and not (root / "public").is_dir():
        parser.error(f"{root} holds neither a private/ nor a public/ folder")

    source: dict[StoreName, ObjectStore] = {
        "private": LocalPrivateStorage(root / "private", max_bytes=config.storage_max_object_bytes),
        "public": LocalPublicStorage(root / "public", max_bytes=config.storage_max_object_bytes),
    }
    target: dict[StoreName, ObjectStore] = {
        "private": get_private_storage(),
        "public": get_public_storage(),
    }
    with session_scope() as db:
        refs = file_references(db)
        db.rollback()  # nothing was written; leave nothing to commit
    outcomes = copy_files(refs, source, target, execute=args.execute)
    heading = "Copied" if args.execute else "Dry run, nothing written"
    sys.stdout.write(f"{heading} ({config.file_storage_provider}):\n{report(outcomes)}\n")
    return 1 if any(o.result in PROBLEMS for o in outcomes) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
