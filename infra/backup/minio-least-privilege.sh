#!/usr/bin/env bash
# Least-privilege MinIO users for the backup tests and the CI drill (BK-17).
# A laptop and CI only: MinIO here is the stand-in for the real provider,
# and every value below is a development-only value, never a real key.
#
#   MC="docker exec -i markx-minio mc" infra/backup/minio-least-privilege.sh
#
# MC is the MinIO client command (inside the MinIO container is simplest);
# MINIO_URL is MinIO's address as MC sees it (default http://127.0.0.1:9000).
# Safe to run again.
#
# The users and what each may do (docs/runbooks/backup-and-restore.md):
#
#   markx-backup-writer-dev-only     the SERVER's backup key: add, read and list
#                                    the backup bucket, and list its versions (to
#                                    see a file written again, RN-1); extend (never
#                                    shorten) an object lock; abort its own
#                                    unfinished uploads. It can NOT delete
#                                    anything (BK-1).
#   markx-backup-reader-dev-only     the RECOVERY MACHINE's key: read and list only,
#                                    older versions included (an older locked copy
#                                    of a file written again, RN-1).
#   markx-backup-retention-dev-only  the RETENTION job's key, off the server:
#                                    read, list and delete (every version).
#   markx-source-reader-dev-only     reads the two file buckets; never writes.
#   markx-restore-target-dev-only    makes, fills and removes the drill's own
#                                    throwaway buckets (markx-drill-*) only.
set -euo pipefail

MC="${MC:-mc}"
URL="${MINIO_URL:-http://127.0.0.1:9000}"
ROOT_USER="${MINIO_ROOT_USER:-markx-dev-only}"
ROOT_PASSWORD="${MINIO_ROOT_PASSWORD:-markx-minio-dev-only-password}"
ALIAS=markxlp

# The backup buckets: CI's markx-backups and the tests' markx-test-backups-*.
BACKUP_BUCKETS='"arn:aws:s3:::markx-backups", "arn:aws:s3:::markx-test-backups-*"'
BACKUP_OBJECTS='"arn:aws:s3:::markx-backups/*", "arn:aws:s3:::markx-test-backups-*/*"'
# The file buckets: CI's and the tests' (markx-test-files-<run>-private and -public).
# (MinIO matches a wildcard at the end of a bucket name only.)
SOURCE_BUCKETS='"arn:aws:s3:::markx-private", "arn:aws:s3:::markx-public", "arn:aws:s3:::markx-test-files-*"'
SOURCE_OBJECTS='"arn:aws:s3:::markx-private/*", "arn:aws:s3:::markx-public/*", "arn:aws:s3:::markx-test-files-*/*"'

$MC alias set "$ALIAS" "$URL" "$ROOT_USER" "$ROOT_PASSWORD" >/dev/null

policy() {  # name, statements
  local name="$1" statements="$2"
  printf '{"Version": "2012-10-17", "Statement": [%s]}' "$statements" \
    | $MC admin policy create "$ALIAS" "$name" /dev/stdin >/dev/null
}

user() {  # access key, secret key, policy
  $MC admin user add "$ALIAS" "$1" "$2" >/dev/null
  $MC admin policy attach "$ALIAS" "$3" --user "$1" >/dev/null 2>&1 || true
}

policy markx-backup-writer "
  {\"Effect\": \"Allow\", \"Action\": [\"s3:ListBucket\", \"s3:ListBucketVersions\", \"s3:GetBucketLocation\",
    \"s3:GetBucketObjectLockConfiguration\", \"s3:GetBucketVersioning\",
    \"s3:ListBucketMultipartUploads\"], \"Resource\": [$BACKUP_BUCKETS]},
  {\"Effect\": \"Allow\", \"Action\": [\"s3:PutObject\", \"s3:GetObject\",
    \"s3:GetObjectRetention\", \"s3:PutObjectRetention\", \"s3:AbortMultipartUpload\",
    \"s3:ListMultipartUploadParts\"], \"Resource\": [$BACKUP_OBJECTS]}"

policy markx-backup-reader "
  {\"Effect\": \"Allow\", \"Action\": [\"s3:ListBucket\", \"s3:ListBucketVersions\",
    \"s3:GetBucketLocation\", \"s3:GetBucketObjectLockConfiguration\"],
    \"Resource\": [$BACKUP_BUCKETS]},
  {\"Effect\": \"Allow\", \"Action\": [\"s3:GetObject\", \"s3:GetObjectVersion\",
    \"s3:GetObjectRetention\"], \"Resource\": [$BACKUP_OBJECTS]}"

policy markx-backup-retention "
  {\"Effect\": \"Allow\", \"Action\": [\"s3:ListBucket\", \"s3:ListBucketVersions\",
    \"s3:GetBucketLocation\", \"s3:GetBucketObjectLockConfiguration\",
    \"s3:GetBucketVersioning\"], \"Resource\": [$BACKUP_BUCKETS]},
  {\"Effect\": \"Allow\", \"Action\": [\"s3:GetObject\", \"s3:GetObjectVersion\",
    \"s3:GetObjectRetention\", \"s3:DeleteObject\", \"s3:DeleteObjectVersion\"],
    \"Resource\": [$BACKUP_OBJECTS]}"

policy markx-source-reader "
  {\"Effect\": \"Allow\", \"Action\": [\"s3:ListBucket\", \"s3:GetBucketLocation\"],
    \"Resource\": [$SOURCE_BUCKETS]},
  {\"Effect\": \"Allow\", \"Action\": [\"s3:GetObject\"], \"Resource\": [$SOURCE_OBJECTS]}"

policy markx-restore-target "
  {\"Effect\": \"Allow\", \"Action\": [\"s3:CreateBucket\", \"s3:DeleteBucket\",
    \"s3:ListBucket\", \"s3:GetBucketLocation\", \"s3:GetBucketPolicy\"],
    \"Resource\": [\"arn:aws:s3:::markx-drill-*\"]},
  {\"Effect\": \"Allow\", \"Action\": [\"s3:PutObject\", \"s3:GetObject\", \"s3:DeleteObject\"],
    \"Resource\": [\"arn:aws:s3:::markx-drill-*/*\"]},
  {\"Effect\": \"Allow\", \"Action\": [\"s3:ListAllMyBuckets\"], \"Resource\": [\"arn:aws:s3:::*\"]}"

user markx-backup-writer-dev-only markx-backup-writer-dev-only-secret markx-backup-writer
user markx-backup-reader-dev-only markx-backup-reader-dev-only-secret markx-backup-reader
user markx-backup-retention-dev-only markx-backup-retention-dev-only-secret markx-backup-retention
user markx-source-reader-dev-only markx-source-reader-dev-only-secret markx-source-reader
user markx-restore-target-dev-only markx-restore-target-dev-only-secret markx-restore-target

echo "least-privilege MinIO users ready (development only)"
