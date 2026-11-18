"""What every file store promises (D-090), on the local folders and on a
real MinIO server: round trips, missing objects, refused content, refused
keys, bounded reads, short-lived links, and failures that name nothing."""

from __future__ import annotations

import io
import logging
import socket
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image

from markx.core.storage import (
    MAX_SIGNED_URL_SECONDS,
    LocalPrivateStorage,
    LocalPublicStorage,
    ObjectStorageSettings,
    ObjectStore,
    S3ObjectStore,
    StorageUnavailable,
    StoredFileMissing,
    StoredFileRefused,
    _check_integrity,
    make_s3_client,
    sniff_image_type,
)
from tests.storage.conftest import SECRET_KEY


def picture(fmt: str = "PNG", size: tuple[int, int] = (24, 16)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (30, 90, 200)).save(buffer, fmt)
    return buffer.getvalue()


TYPES = [("PNG", "image/png"), ("JPEG", "image/jpeg"), ("WEBP", "image/webp")]


@pytest.fixture(params=["local", "minio"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[ObjectStore]:
    """The private store of each adapter."""
    if request.param == "local":
        yield LocalPrivateStorage(tmp_path / "private")
    else:
        private, _ = request.getfixturevalue("stores")
        yield private


# -- the contract ----------------------------------------------------------------------


@pytest.mark.parametrize(("fmt", "content_type"), TYPES)
def test_a_picture_goes_in_and_comes_back_unchanged(
    store: ObjectStore, fmt: str, content_type: str
) -> None:
    data = picture(fmt)
    key = f"contract/{fmt.lower()}-roundtrip"
    store.put(key, data, content_type)
    assert store.exists(key)
    assert store.get(key) == data
    info = store.head(key)
    assert (info.key, info.size, info.content_type) == (key, len(data), content_type)
    assert info.last_modified is not None


def test_deleting_removes_the_object_and_is_safe_to_repeat(store: ObjectStore) -> None:
    store.put("contract/to-delete", picture(), "image/png")
    store.delete("contract/to-delete")
    assert not store.exists("contract/to-delete")
    store.delete("contract/to-delete")  # nothing there: no error
    with pytest.raises(StoredFileMissing):
        store.get("contract/to-delete")


def test_a_missing_object_is_missing_not_an_outage(store: ObjectStore) -> None:
    assert not store.exists("contract/never-written")
    with pytest.raises(StoredFileMissing):
        store.get("contract/never-written")
    with pytest.raises(StoredFileMissing):
        store.head("contract/never-written")


@pytest.mark.parametrize(
    ("data", "content_type", "reason"),
    [
        (b"<html><script>alert(1)</script></html>", "text/html", "not an allowed picture type"),
        (b"%PDF-1.7 a document", "application/pdf", "not an allowed picture type"),
        (b"GIF89a" + b"\x00" * 32, "image/gif", "not an allowed picture type"),
        # The declared type must be what the bytes are.
        (b"<svg onload=alert(1)>", "image/png", "not a image/png picture"),
        (picture("JPEG"), "image/png", "not a image/png picture"),
        (picture("PNG"), "image/webp", "not a image/webp picture"),
        (b"", "image/png", "empty"),
    ],
)
def test_only_real_pictures_of_the_declared_type_are_stored(
    store: ObjectStore, data: bytes, content_type: str, reason: str
) -> None:
    with pytest.raises(StoredFileRefused, match=reason):
        store.put("contract/refused", data, content_type)
    assert not store.exists("contract/refused")


@pytest.mark.parametrize(
    "key",
    ["../outside", "/etc/passwd", "a/../../b", "a//b", "A/B", "", "a b", "a?b", "a%2fb",
     "x" * 201, "seller-documents/../../x"],
)  # fmt: skip
def test_a_key_that_could_escape_or_surprise_is_refused(store: ObjectStore, key: str) -> None:
    for attempt in (
        lambda: store.put(key, picture(), "image/png"),
        lambda: store.get(key),
        lambda: store.head(key),
        lambda: store.exists(key),
        lambda: store.delete(key),
    ):
        with pytest.raises(StoredFileRefused, match="unsafe storage key"):
            attempt()


def test_nothing_larger_than_the_limit_is_written(
    tmp_path: Path, minio: ObjectStorageSettings
) -> None:
    data = picture(size=(200, 200))
    small = replace(minio, max_bytes=len(data) - 1)
    client = make_s3_client(small)
    try:
        for store in (
            LocalPrivateStorage(tmp_path, max_bytes=len(data) - 1),
            S3ObjectStore(client, minio.private_bucket, name="private", settings=small),
        ):
            with pytest.raises(StoredFileRefused, match="larger than"):
                store.put("contract/too-large", data, "image/png")
            assert not store.exists("contract/too-large")
    finally:
        client.close()


def test_nothing_larger_than_the_limit_is_read(minio: ObjectStorageSettings) -> None:
    """An object put in the bucket by something else, larger than MarkX ever
    writes, is refused before it is read into memory."""
    data = picture(size=(200, 200))
    client = make_s3_client(minio)
    try:
        client.put_object(Bucket=minio.private_bucket, Key="contract/huge", Body=data)
        small = replace(minio, max_bytes=len(data) - 1)
        store = S3ObjectStore(client, minio.private_bucket, name="private", settings=small)
        with pytest.raises(StorageUnavailable) as refused:
            store.get("contract/huge")
        assert refused.value.reason == "object_too_large"
    finally:
        client.close()


def test_rendered_pictures_are_cacheable_and_private_files_are_not(
    stores: tuple[S3ObjectStore, S3ObjectStore], minio: ObjectStorageSettings
) -> None:
    private, public = stores
    private.put("contract/source", picture(), "image/png")
    public.put("contract/thumb.webp", picture("WEBP"), "image/webp")
    client = make_s3_client(minio)
    try:
        assert (
            client.head_object(Bucket=minio.private_bucket, Key="contract/source")["CacheControl"]
            == "no-store"
        )
        public_head = client.head_object(Bucket=minio.public_bucket, Key="contract/thumb.webp")
        assert public_head["CacheControl"] == "public, max-age=31536000, immutable"
        assert public_head["ContentType"] == "image/webp"
        # Two buckets: nothing written to one appears in the other.
        assert not public.exists("contract/source")
        assert not private.exists("contract/thumb.webp")
    finally:
        client.close()


def test_bytes_that_do_not_match_their_checksum_are_refused(
    stores: tuple[S3ObjectStore, S3ObjectStore],
) -> None:
    private, _ = stores
    data = picture()
    _check_integrity(private, None, data)  # no checksum to compare: accepted
    _check_integrity(private, '"abc-2"', data)  # a multipart ETag is not an MD5: accepted
    with pytest.raises(StorageUnavailable) as refused:
        _check_integrity(private, '"' + "0" * 32 + '"', data)
    assert refused.value.reason == "checksum_mismatch"


def test_the_picture_type_comes_from_the_bytes() -> None:
    for fmt, content_type in TYPES:
        assert sniff_image_type(picture(fmt)) == content_type
    for data in (b"", b"GIF89a", b"RIFF\x00\x00\x00\x00WAVE", b"<html>"):
        assert sniff_image_type(data) is None


# -- links straight to an object ---------------------------------------------------------


def _status(url: str) -> int:
    try:
        with urllib.request.urlopen(url, timeout=5) as answer:  # noqa: S310
            return int(answer.status)
    except urllib.error.HTTPError as refused:
        return refused.code


def test_a_signed_link_works_until_it_expires(stores: tuple[S3ObjectStore, S3ObjectStore]) -> None:
    private, _ = stores
    private.put("contract/linked", picture(), "image/png")
    url = private.signed_url("contract/linked", expires_in=1)
    assert _status(url) == 200
    time.sleep(2.2)
    assert _status(url) == 403


def test_a_signed_link_never_lives_longer_than_five_minutes(store: ObjectStore) -> None:
    for seconds in (0, -1, MAX_SIGNED_URL_SECONDS + 1, 86_400):
        with pytest.raises(ValueError, match="between 1 and 300 seconds"):
            store.signed_url("contract/linked", expires_in=seconds)


def test_the_laptop_folders_make_no_links(tmp_path: Path) -> None:
    with pytest.raises(StorageUnavailable) as refused:
        LocalPublicStorage(tmp_path).signed_url("contract/linked", expires_in=60)
    assert refused.value.reason == "signed_links_need_object_storage"


def test_the_private_bucket_refuses_a_reader_without_credentials(
    stores: tuple[S3ObjectStore, S3ObjectStore], minio: ObjectStorageSettings
) -> None:
    private, _ = stores
    private.put("contract/private", picture(), "image/png")
    assert _status(f"{minio.endpoint_url}/{minio.private_bucket}/contract/private") == 403
    assert _status(f"{minio.endpoint_url}/{minio.private_bucket}") == 403  # no listing either
    assert private.readable_without_credentials("contract/private") is False


# -- failures --------------------------------------------------------------------------


def _assert_names_nothing(
    error: StorageUnavailable, settings: ObjectStorageSettings, caplog: pytest.LogCaptureFixture
) -> None:
    # Every field of every log record, as the JSON log writes them, not only
    # the message line.
    logged = " ".join(str(vars(record)) for record in caplog.records)
    assert caplog.records, "a failure is logged"
    said = error.message + str(error.details) + error.reason + caplog.text + logged
    for secret in (
        settings.secret_access_key,
        SECRET_KEY,
        settings.private_bucket,
        settings.endpoint_url or "",
        "contract/",
    ):
        assert secret not in said
    assert error.status_code == 503
    assert error.code == "storage_unavailable"


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"secret_access_key": "test-only-wrong-secret"}, "SignatureDoesNotMatch"),
        ({"access_key_id": "test-only-no-such-key"}, "InvalidAccessKeyId"),
    ],
)
def test_wrong_credentials_are_refused_and_named_nowhere(
    minio: ObjectStorageSettings,
    caplog: pytest.LogCaptureFixture,
    change: dict[str, str],
    reason: str,
) -> None:
    wrong = replace(minio, **change)
    client = make_s3_client(wrong)
    store = S3ObjectStore(client, minio.private_bucket, name="private", settings=wrong)
    caplog.set_level(logging.ERROR, logger="markx.storage")
    try:
        for attempt in (
            lambda: store.put("contract/creds", picture(), "image/png"),
            lambda: store.get("contract/creds"),
            store.check_reachable,
        ):
            with pytest.raises(StorageUnavailable) as refused:
                attempt()
            assert refused.value.reason in (reason, "403")
            _assert_names_nothing(refused.value, wrong, caplog)
    finally:
        client.close()


def test_a_bucket_that_does_not_exist_is_an_outage(
    minio: ObjectStorageSettings, caplog: pytest.LogCaptureFixture
) -> None:
    client = make_s3_client(minio)
    store = S3ObjectStore(client, "markx-test-no-such-bucket", name="private", settings=minio)
    try:
        with pytest.raises(StorageUnavailable) as refused:
            store.put("contract/nowhere", picture(), "image/png")
        assert refused.value.reason == "NoSuchBucket"
        # A missing bucket is not a missing file: it must never read as "not found".
        with pytest.raises(StorageUnavailable):
            store.get("contract/nowhere")
    finally:
        client.close()


def test_an_unreachable_store_fails_at_once(
    minio: ObjectStorageSettings, caplog: pytest.LogCaptureFixture
) -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    dead = replace(minio, endpoint_url=f"http://127.0.0.1:{port}", connect_timeout=1.0)
    client = make_s3_client(dead)
    store = S3ObjectStore(client, minio.private_bucket, name="private", settings=dead)
    caplog.set_level(logging.ERROR, logger="markx.storage")
    started = time.monotonic()
    try:
        with pytest.raises(StorageUnavailable) as refused:
            store.put("contract/dead", picture(), "image/png")
    finally:
        client.close()
    assert refused.value.reason == "unreachable"
    assert time.monotonic() - started < 5
    _assert_names_nothing(refused.value, dead, caplog)


@pytest.fixture
def silent_server() -> Iterator[str]:
    """Accepts connections and never answers: a provider that hangs."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(8)
    held: list[socket.socket] = []
    stop = threading.Event()

    def accept() -> None:
        server.settimeout(0.2)
        while not stop.is_set():
            try:
                connection, _ = server.accept()
                held.append(connection)
            except TimeoutError:
                continue
            except OSError:
                return

    thread = threading.Thread(target=accept, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.getsockname()[1]}"
    finally:
        stop.set()
        thread.join()
        for connection in held:
            connection.close()
        server.close()


def test_a_store_that_does_not_answer_times_out_quickly(
    minio: ObjectStorageSettings, silent_server: str, caplog: pytest.LogCaptureFixture
) -> None:
    slow = replace(minio, endpoint_url=silent_server, connect_timeout=1.0, read_timeout=0.5)
    client = make_s3_client(slow)
    store = S3ObjectStore(client, minio.private_bucket, name="private", settings=slow)
    caplog.set_level(logging.ERROR, logger="markx.storage")
    started = time.monotonic()
    try:
        with pytest.raises(StorageUnavailable) as refused:
            store.get("contract/slow")
    finally:
        client.close()
    assert refused.value.reason == "timeout"
    # One try and one retry of half a second each, not the SDK's defaults.
    assert time.monotonic() - started < 4
    _assert_names_nothing(refused.value, slow, caplog)
