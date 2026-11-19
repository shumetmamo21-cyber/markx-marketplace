# Independent audit — 19 November 2026

## Contents

- [1. Executive summary](#1-executive-summary)
- [2. Verified repository and branch state](#2-verified-repository-and-branch-state)
- [3. Backup and disaster-recovery audit (deepest section)](#3-backup-and-disaster-recovery-audit-deepest-section)
  - [3A. Cryptographic architecture (verified in `B/crypto.py`)](#3a-cryptographic-architecture-verified-in-bcryptopy)
  - [3B. Manifest and signature security (`B/manifest.py`, `crypto.py:507-535`, `runner.py:447-513`)](#3b-manifest-and-signature-security-bmanifestpy-cryptopy507-535-runnerpy447-513)
  - [3C. Database backup correctness (`B/database.py`, `runner.py:411-431`, `references.py`)](#3c-database-backup-correctness-bdatabasepy-runnerpy411-431-referencespy)
  - [3D. Uploaded-file backup correctness (`B/sources.py`, `runner.py:244-295`, `references.py:43-62`)](#3d-uploaded-file-backup-correctness-bsourcespy-runnerpy244-295-referencespy43-62)
  - [3E. Remote storage (`B/destination.py`, `B/config.py`)](#3e-remote-storage-bdestinationpy-bconfigpy)
  - [3F. Restore and disaster recovery (`B/restore.py`, `__main__.py:275-339`)](#3f-restore-and-disaster-recovery-brestorepy-__main__py275-339)
  - [3G. Automated restore drills (`B/drill.py`, `ci.yml:102-142`, tests)](#3g-automated-restore-drills-bdrillpy-ciyml102-142-tests)
  - [3H. Monitoring, retention and operational readiness](#3h-monitoring-retention-and-operational-readiness)
  - [3I. Verified strengths (backup)](#3i-verified-strengths-backup)
- [4. Backup threat model](#4-backup-threat-model)
- [5. Backup findings and severity](#5-backup-findings-and-severity)
- [6. Backup activation readiness](#6-backup-activation-readiness)
- [7. Blueprint requirements matrix (summary; 57 rows from sub-review, key rows spot-checked)](#7-blueprint-requirements-matrix-summary-57-rows-from-sub-review-key-rows-spot-checked)
- [8. Backend audit (sub-review; H1 and M6 spot-checked)](#8-backend-audit-sub-review-h1-and-m6-spot-checked)
- [9. Security audit](#9-security-audit)
- [10. Frontend audit (sub-review)](#10-frontend-audit-sub-review)
- [11. Marketplace business logic](#11-marketplace-business-logic)
- [12. Integration status](#12-integration-status)
- [13. Infrastructure audit (sub-review)](#13-infrastructure-audit-sub-review)
- [14. CI and testing audit](#14-ci-and-testing-audit)
- [15. Release readiness scorecard (estimates, marked as opinion; not percentages of "done")](#15-release-readiness-scorecard-estimates-marked-as-opinion-not-percentages-of-done)
- [16. All P0 and P1 findings](#16-all-p0-and-p1-findings)
- [17. Prioritized implementation roadmap (safest order)](#17-prioritized-implementation-roadmap-safest-order)
  - [P0 (critical)](#p0-critical)
  - [P1 (launch blockers)](#p1-launch-blockers)
  - [P2 (Release 1 completion)](#p2-release-1-completion)
  - [P3 (improvements)](#p3-improvements)
- [18. Founder decisions required](#18-founder-decisions-required)
- [19. External services and costs eventually required](#19-external-services-and-costs-eventually-required)
- [20. Safe to build next without external infrastructure](#20-safe-to-build-next-without-external-infrastructure)
- [21. What is NOT verified](#21-what-is-not-verified)
- [22. Final recommendation](#22-final-recommendation)
- [After approval (execution note)](#after-approval-execution-note)

---

# MarkX: Independent Engineering, Security and Release-Readiness Audit

**Date:** 2026-11-19
**Mode:** strictly read-only. Nothing was edited, checked out, committed, pushed, installed, deployed or connected.
**How evidence was gathered:** I read git objects directly with `git show` / `git grep` on `origin/claude/project-scaffold` and checked GitHub Actions through the API.
- I read the backup subsystem (`apps/api/markx/backup/*`) line by line myself.
- Three read-only sub-reviews covered backend/security, infra/CI/frontend and blueprint coverage. I spot-checked their key claims (marked "spot-checked"). The rest is marked as sub-review evidence.

Paths are relative to the repo root. `B/` means `apps/api/markx/backup/`.

---

## 1. Executive summary

- **The backup system is serious, competent engineering, but it is not yet safe to activate as designed.**
  - Verified strengths:
    - Encryption uses a modern, maintained library (X25519 + HKDF-SHA256 + AES-256-GCM in a STREAM construction).
    - Signed manifests, a consistent database snapshot, read-back verification of every upload, and strict restore-target checks.
    - A real drill runs in CI.
  - Four properties undermine the promises it makes:
    1. **The production server holds a credential that can delete every remote backup**, and nothing requires or checks object lock or versioning. A compromised server, or an attacker holding `backup.env`, can erase all recovery points. (**P0**)
    2. **The monthly drill procedure brings the recovery key onto the production server**, which breaks the core rule that the server never holds it. (**P0 process / High**)
    3. **A file copy that fails read-back verification stays at the destination and is silently reused** by later incremental runs, which mark the set "complete, verified". The damage is found only at restore or drill time. (**High**)
    4. **All backup alerting runs on the same server it watches**, and no alert channel exists. A total server loss produces no alert at all. (**High**)
- **The marketplace codebase is far more complete than a typical pre-launch project.**
  - 887 API test functions, CI green on the reported HEAD, careful authentication, sessions, stock and checkout code.
  - **Nothing is deployed, connected or proven against a real provider.** Every external dependency (SMS, Telegram bot, S3/R2, domain/TLS, CDN, monitoring, payments, couriers) is either an adapter tested against fakes or MinIO, or does not exist.
- **Repository state is a real finding.**
  - `main` contains only "Initial commit".
  - All work (124 commits) sits on `claude/project-scaffold` behind **PR #1 (open, unmerged)**.
  - Two other `claude/*` branches have diverged from it.
- **Overall position (opinion):** code-complete for most of the Release 1 core loop. Not ready for staging with real data, not ready for production. Backup activation must wait for the P0 fixes below.

## 2. Verified repository and branch state

| Item | Verified fact | Evidence |
|---|---|---|
| Remote `main` HEAD | `617a276` "Initial commit", 1 commit, README only | `git ls-remote`, `git log origin/main` |
| Reported HEAD `373c082` | Exists, as the tip of **`claude/project-scaffold`**, not `main` (124 commits) | `git log origin/claude/project-scaffold` |
| PR | #1 "Scaffold MarkX marketplace monorepo", **open, not merged**, head 373c082 → base main | GitHub API |
| CI on 373c082 | CI #131 (push) and #132 (PR): **success** | Actions runs 44389549254, 44389560101 |
| Browser journeys on 373c082 | **Not run.** Journeys #21 passed on parent `937c410`. 373c082 is a docs-only status commit. Journeys run on push only, with a path filter | Actions; `journeys.yml:11-17` |
| Other branches | `claude/markx-seller-management-oag1a4` (17 commits), `claude/markx-third-session-cq58yj` (24 commits, notes "divergence from project-scaffold") | `git log` |
| Commit identity | Commits by the repo owner, co-authored with an AI session | Commit trailers |
| Size | 464 tracked files; API 144 modules; 21 migrations; web 126 source files; 10 e2e scripts | `git ls-tree` |

**Risk:** the working tree of this audit branch is empty, and the source of truth lives only on an unmerged feature branch. Losing that branch, or an accidental force-push, would lose all the code. There is no evidence of branch protection.

---

## 3. Backup and disaster-recovery audit (deepest section)

### 3A. Cryptographic architecture (verified in `B/crypto.py`)

| Question | Finding |
|---|---|
| Algorithm | `X25519-HKDF-SHA256/AES-256-GCM-STREAM` (`crypto.py:72`). Each file gets a fresh ephemeral X25519 key and a 16-byte salt. The HKDF info binds `epk` and the recipient public key (`:293-299`). |
| Library | `cryptography` 50.0.2 (`apps/api/uv.lock`), which is maintained and appropriate. No hand-rolled primitives. |
| Nonces | 8-byte chunk counter + 3 zero bytes + a 1-byte "last" flag (`:302-303`). The key is unique per file, so counter nonces are safe. |
| Header integrity | The whole raw header (magic, length, JSON) is the associated data for every chunk (`:376, :384, :473`). The header length is capped at 1 KiB and the chunk size is bounded (`:75-77, :424, :441`). |
| Truncation, reordering, extension | The STREAM "last" flag plus the counter detect a dropped tail, swapped, repeated or appended chunks (`:466-482`). A file that is an exact multiple of the chunk size is handled because the encryptor holds back the final chunk (`:373`). **Verified correct by reading.** |
| Low-order or invalid `epk` | `exchange()` raises `ValueError`, which is mapped to `DecryptionError` (`:459-462`). |
| Does the server hold only the public key? | **Yes for encryption.** The backup service loads `backup-public.key` and `signing.key` only (`__main__.py:91-106`). `deploy.sh check` refuses a recovery key under `/etc/markx` (`infra/production/deploy.sh:102-105`). |
| Can the server decrypt? | **Not in normal operation.** **Yes during the documented monthly drill**: the runbook copies `recovery.key` into `/root/recovery` on the production server and mounts it into the backup container (`docs/runbooks/backup-and-restore.md:178-197`). The runbook admits this "puts the recovery key there for minutes". |
| Recovery on a new machine | Designed for it. A restore needs only the destination's read credentials, `recovery.key`, `signer-public.key`, a PostgreSQL 17 server and a checkout or image containing `bootstrap.sh` (`config.py:19-21`, `restore.py`). **NOT VERIFIED** on a separate machine against a real provider. |
| Recovery key independent of the server | Yes. It is generated by `keygen` on an operator machine (`__main__.py:129-148`). |
| Key loss | **Permanent loss** of every set encrypted to that key, by design. There is no escrow, no Shamir split, no passphrase wrapping. The key file is raw base64 in plaintext (`crypto.py:214-218`). Custody is founder decision F-19, still open. |
| Rotation | Key rings are supported for decryption (`decrypt_stream` accepts a dict, `:446-458`; `--recovery-key` is repeatable). The blob catalog is keyed per key pair, so old-key blobs are never reused (`runner.py:200-203`; test `test_after_a_key_rotation_no_blob_of_the_old_key_is_reused`). Old sets stay recoverable **only if the old recovery key is kept**. There is no tool to re-encrypt old sets (documented gap). |
| Signing-key rotation side effect | The blob name key is derived from the **signing** key's seed (`crypto.py:155-163, :500-504`). Rotating the signing key renames every blob, so the next backup re-uploads every file (a cost and duration spike). Retention trusts only the current signer (`__main__.py:174-175`), so sets signed by the old key become "untrusted" and are **kept forever** (safe, but storage grows without limit). |
| Leakage | Plaintext never goes to disk: the dump is streamed into the encryptor (`database.py:142-177`). PG credentials travel only in the child process's environment, never in argv, and `MARKX_*`/`AWS_*` variables are stripped from children (`database.py:83-93`). Evidence files kept on the server: `pg_dump.stderr`, the `pg_restore --list` table of contents (schema names, no data), and a 12-frame traceback (`runner.py:373-381`). These are acceptable. The manifest is plaintext and holds table names, per-table row counts, release, DB name and server version. That is a metadata leak to anyone who can read the bucket (Low). |
| Key-file hygiene | Secret key files are refused if group or other bits are set (`crypto.py:255-259`). `keygen` never overwrites (`O_EXCL`, `:279-288`). |

**Verdict 3A:** the cryptography is sound and correctly implemented for confidentiality and integrity against a **bucket-only** attacker. The weak points are operational (key custody, the drill), not algorithmic.

### 3B. Manifest and signature security (`B/manifest.py`, `crypto.py:507-535`, `runner.py:447-513`)

- **What is signed.** Canonical JSON (sorted keys, ASCII) of the whole manifest plus `signer_key_id`, with a domain-separation prefix `markx-backup-manifest/2\0`. The algorithm is Ed25519.
- **The manifest binds:**
  - the backup id (verified against the requested id, `manifest.py:84-86`);
  - the dump's ciphertext and plaintext SHA-256 and sizes;
  - the encrypted file index's ciphertext and plaintext SHA-256;
  - `blobs.txt` SHA-256;
  - object counts, total bytes, per-store counts, every table's row count, the alembic revision, the release and the completeness status.
- **Blobs are bound only indirectly.** The signed index hash → the index → each entry's plaintext SHA-256 and size. Restore checks every blob's decrypted SHA-256 against the index (`restore.py:381-383`). Substituting a blob with another valid MXB2 file (anyone with the public key can make one) is therefore **detected at restore**. It is **not detected by the default `verify`** (`deep=False` checks presence only, `restore.py:280-283`).
- **Verification order:** the signature is checked first, then the hash of each downloaded piece, then a full trial decryption of the dump and index, and only then the target checks and writes (`restore.py:205-260, 524-531`). **Verified.**
- **Incomplete sets** are refused unless `--accept-incomplete` is given (`restore.py:207-213`). A missing manifest means the set does not exist (`restore.py:142-143`).
- **Where the signing key lives:** **on the production server** (`/etc/markx/backup-signing.key`, mounted read-only into the backup container, `infra/production/compose.yaml:296, 303`).

**Encryption vs integrity vs authenticity:**
- **Encryption (MXB2)** gives confidentiality plus integrity of each file. It gives no authorship, because anyone holding the public key can produce a valid file.
- **The manifest signature** gives authenticity: the set was produced by whoever holds the signing key.
- **The hash chain** (signed manifest → hashes → index → per-file hashes) gives set completeness and binding.

**Remaining trust assumptions (critical to understand):**
1. **A compromised production server can forge fully valid backup sets.** It holds the public key and the signing key, so it can create a signed manifest for a dump containing anything. Signatures protect against a *bucket* attacker, **not** a *server* attacker.
2. **A malicious dump is executable content.** `pg_restore` of an attacker-supplied custom archive runs arbitrary SQL as the restoring role. The runbook restores and drills as `PGUSER=postgres`, a **superuser** (runbook lines 190-193). A superuser can run `COPY … TO PROGRAM`, i.e. execute shell commands on the database host. So a server compromise can be carried into the recovery environment.
3. Retention deletes based on signatures from the current signing key only. An attacker with the signing key could plant "complete" sets to push genuine sets out of the `min_sets` window. That needs the server anyway, and point 1 is the bigger issue.

### 3C. Database backup correctness (`B/database.py`, `runner.py:411-431`, `references.py`)

- **Consistency: verified.** A `REPEATABLE READ, READ ONLY` transaction exports its snapshot. `pg_dump --snapshot=<id>` dumps exactly that snapshot, and the same transaction reads row counts and file references (`runner.py:413-430`).
- **PostgreSQL 17.** Production tools are copied from `postgres:17.12` into the backup image (per DECISIONS). CI uses a floating `postgres:17` tag (`ci.yml:117-119`), so the exact version is not pinned in tests.
- **Dump acceptance checks:**
  - pg_dump exit code 0, non-empty output, the `PGDMP` magic;
  - `pg_restore --list` exit code 0;
  - every `public` table present in the table of contents;
  - `alembic_version` data present (`database.py:178-195`).
- **Roles.** Roles are not dumped (no `pg_dumpall --globals`). They are recreated by `bootstrap.sh` on restore. This is acceptable because the roles are fixed, but **hazard:** the runbook says to always pass `MARKX_DB_*_PASSWORD` to a restore or drill on a server, and bootstrap **resets** role passwords whenever those variables are given (`infra/postgres/bootstrap.sh:14-25`). Roles are cluster-wide, so a typo during a drill on the production cluster **changes production role passwords and breaks the live app** (Medium).
- **Row-count verification:** every public table's exact count is compared after restore (`restore.py:423-433`). Invalid indexes and unvalidated constraints are checked (`references.py:102-119`). The migration revision is compared. The audit log must still be non-updatable by `markx_app` (`restore.py:465-474`). **Verified by reading.**
- **First deployment / unmigrated database:** handled. The revision is `None`, file references are empty, and there is a test (`test_a_database_not_yet_migrated_backs_up_and_restores_as_empty`).
- **Concurrency:** a file lock plus a PostgreSQL advisory lock; a second run is recorded as `skipped` (`runner.py:146-179`). Tested.
- **Interruption:** the manifest is written last, so a set without a manifest does not exist; leftover blobs are reused; stale multipart uploads are aborted after 24 h (`runner.py:408`). Tested.
- **Last known good:** a failure never deletes anything remotely; the evidence is kept locally (`runner.py:357-388`). `status.json` is updated only for complete sets (`runner.py:539-540`).
- **Ways a set can be reported successful but be unrecoverable:**
  - **(i) The reused-damaged-blob bug**, see finding BK-3.
  - (ii) A dump that pg_restore lists correctly but fails to *restore* (for example an extension missing on the recovery host). This is caught only by an actual restore, which the drill does.
  - (iii) A set that is "complete" but whose blobs were later deleted or altered at the destination. Not detected until a deep verify or a drill. There is no scheduled deep verification.
  - (iv) Only the `public` schema is counted and checked. Objects outside `public` would be silently uncounted (low risk today).
- **Database role used for backup:** `markx_migrator`, the schema owner (`compose.yaml:292`). Least privilege would be a dedicated read-only role with `pg_read_all_data` (Medium). This password, plus internet egress, sits in the backup container.

### 3D. Uploaded-file backup correctness (`B/sources.py`, `runner.py:244-295`, `references.py:43-62`)

- **Stores:** `private` (seller documents, original/source images, problem/dispute photos) and `public` (processed `-320.webp` / `-1200.webp` renditions). The whole of both buckets is backed up, referenced or not.
- **Reference reconciliation:**
  - `seller_documents.file_key`, `problem_photos.file_key`, `product_images.source_key` (private), and the renditions (public) when `processed_at` is set.
  - `stores.logo_key` and `order_items.image_key` are counted as "unclassified", and any non-zero value fails the set. This is a good fail-safe.
  - A missing referenced file makes the set `incomplete`, which restore refuses. Tested.
- **Integrity at the source:** size is always checked; MD5 against the ETag only for single-part, non-KMS objects (`sources.py:141-146`). Multipart or SSE-KMS objects in real S3/R2 get **size-only** checks (Low).
- **Private/public boundary:** the store is recorded per entry. Restore writes private entries only to the private target and refuses identical target names. `check_private` tests anonymous readability of one sample object (`restore.py:481-499`).
- **Metadata preservation:**
  - Content type is **re-derived by sniffing 16 bytes** (`runner.py:241`). It works only because the app stores images only (`core/storage.py:159-168`, `ALLOWED_CONTENT_TYPES`).
  - Restore refuses an entry with an unknown type (`restore.py:384-386`).
  - **Any future non-image upload (for example PDF documents) will back up but fail to restore** (latent, Medium).
  - Original S3 metadata, last-modified times and ACLs are not preserved.
- **Deduplication:** content-addressed by HMAC(signing-derived key, recipient key id + plaintext SHA-256). Identical files share one blob, which is safe because the index maps (store, key) → blob and checks the plaintext hash.
- **Source read-only:** enforced by API shape (only `list` and `open`) and by documentation (a separate read-only key). **Not enforced by checking the credential.** The CI drill uses MinIO root credentials for both source and destination (`ci.yml:124-131`).
- **Changes during the backup:** the design relies on "no MarkX feature deletes or rewrites a file" (`runner.py:11-16`). A file deleted after the snapshot shows up as a missing reference → incomplete (fails safe). A file overwritten mid-read fails the MD5/size check → `corrupt` → incomplete if referenced.
- **Consistency of database and files:** the database is a point-in-time snapshot; the files are a superset listed after it. **Consistent for restore** under the "files are immutable" invariant (an invariant that exists by convention, not enforced in storage).
- **Restore memory:** each blob is fully loaded into memory (`restore.py:301-303`); the index can be up to 512 MB. Acceptable for images of at most 20 MB (documented).

### 3E. Remote storage (`B/destination.py`, `B/config.py`)

| Item | Finding |
|---|---|
| S3 / R2 | One boto3 adapter. **Never exercised against real AWS or Cloudflare** (DEVELOPMENT_STATUS admits this). R2-specific behaviour (no `x-amz-server-side-encryption`, checksum header differences in newer boto3 1.36+, ETag semantics) is **NOT VERIFIED**. With boto3 1.44.5, default request-checksum behaviour against R2 is a known compatibility area that needs a live test. |
| MinIO / local | Tested in CI and locally. Refused on staging and production (`config.py:255-267`). |
| TLS | `https://` is required for the endpoint on real environments (`config.py:262-263`). Certificate verification uses botocore's default (on). |
| Credential isolation | The service refuses the same access key id for source and destination (`config.py:280-288`). It never falls back to the machine's IAM role (`:213-217`). |
| Bucket separation | The backup bucket name must differ from both file buckets (`config.py:243-248`). The comparison is on names only, not on endpoint or account. |
| Public-access rejection | `check_access` tries an **anonymous list** of the prefix (`destination.py:303-314`). An anonymous **read** of objects is not checked at backup time (`anonymous_can_read` exists but is unused there). A bucket policy that allows `GetObject` but not `ListBucket` would pass. Data is encrypted, so impact is limited (Low). |
| "Same-server" rejection | Only by **provider label**: `s3` or `r2` count as off-site. An `s3` destination whose endpoint is the server's own MinIO over https, or a self-hosted service on the same host, passes as `offsite=True` (`config.py:130-133`) (Medium). |
| Multipart | 64 MiB threshold; boto3 aborts failed multipart uploads itself; stale ones are aborted after 24 h. `list_multipart_uploads` is **not paginated** (`destination.py:391`); more than 1000 stale uploads would be partly missed (Low). |
| Read-back | Full download and SHA-256 compare after every upload (`destination.py:339-346`). Good, but it doubles egress (a cost on S3; free on R2). |
| Failed-upload cleanup | **Missing for verification failures:** the bad object is left in place (BK-3). |
| Versioning / object lock | **Not required, not checked, not compatible with the code's deletes.** The runbook says "versioning or object lock if offered" (`backup-and-restore.md:293-308`). Retention issues plain `DeleteObject` without version ids (`destination.py:383-385`). On a versioned bucket that only creates delete markers, so storage grows without limit unless lifecycle rules are added. Neither is designed. |
| **Can a compromised server destroy backups?** | **Yes.** The destination key must allow `DeleteObject` (runbook step 3), because `serve` runs retention automatically on the server (`__main__.py:225-231`). An attacker with root on the server, or a stolen `backup.env`, can delete every set, every blob and the manifests. With versioning but no object lock, they could also delete versions if the key allows `DeleteObjectVersion`. **This is the single most important backup weakness (BK-1).** |

### 3F. Restore and disaster recovery (`B/restore.py`, `__main__.py:275-339`)

- **Isolated database:** the target must not exist, must not carry the source's name, must not be a system database, and the operator must type the name again as confirmation (`restore.py:324-342`). Verified.
- **Empty isolated storage:** the two targets must be distinct and empty, and must not be the live buckets (`restore.py:345-353`).
  - The live-bucket list comes from `MARKX_BACKUP_SOURCE_*` (`__main__.py:284-286`), which **is not set on a fresh recovery machine**, so that guard is empty there. The emptiness check remains the real protection (Low).
- **Production-target protection:** a restore *can* run against the production PostgreSQL cluster, into a new database name. Bootstrap there can reset role passwords (see 3C). There is no "this is the production cluster" interlock (Medium).
- **Checks on the restored copy:** signature, encryption, hashes, row counts, indexes and constraints, audit-log protection, file checksums with read-back, reference-to-file resolution, and a spot check of the first 50 references through the store (`restore.py:456-462`). Verified.
- **Failure handling:** a database error drops only the database it created. A file-restore failure leaves the database in place with the report marked FAILED. Unexpected exception types (for example `psycopg.Error`, `StorageUnavailable`, `KeyError`) are not caught: the database is left behind with no "FAILED" report (Low).
- **Undocumented or manual steps for total recovery:**
  1. A new server with Docker, a checkout or the images, and `/etc/markx/*` secrets. Application secrets (`MARKX_SECRET_KEY`, `MARKX_ENCRYPTION_KEY`) are **not in the backup**. Without the original `MARKX_ENCRYPTION_KEY`, encrypted columns (for example staff TOTP secrets, `accounts/models.py totp_secret_encrypted`) **cannot be decrypted** after restore. Without the original `MARKX_SECRET_KEY`, handover codes and signed links change. There is no runbook step to escrow these secrets off-server (**High, BK-5**).
  2. The rename or swap of the restored DB into place ("swap names by hand"), new file buckets, CDN and DNS repointing, `MARKX_PUBLIC_MEDIA_BASE_URL`: all manual and unrehearsed.
  3. TLS certificate re-issue (no tooling, per the infra review).
- **Is restore sufficient for total server loss?** The **data path is sufficient in design**, given the recovery key, signer key, bucket read credentials **and** the application secrets. Today it is **not sufficient in practice**, because application-secret escrow is missing and nothing has been rehearsed on a separate machine against a real provider.

### 3G. Automated restore drills (`B/drill.py`, `ci.yml:102-142`, tests)

- **What it proves (in CI, MinIO, demo data):**
  - one backup encrypted and uploaded;
  - a deep verify (every blob decrypted);
  - a restore into a new database and new buckets with row counts, checksums and references matching;
  - seven injected failures refused: changed dump, cut-short index, missing manifest, edited manifest, missing blob, wrong recovery key, and a refused restore writes nothing;
  - cleanup of drill-created resources only.
  - CI fails if "DRILL PASSED" is absent.
- **What it does NOT prove:**
  - A real S3 or R2 provider, real TLS, real latency, real IAM least privilege. CI uses root keys for everything.
  - Recovery **without the original server** or on a different machine.
  - Restore time at production volume (the 4-hour RTO target is unmeasured).
  - The incremental-reuse path over a damaged existing blob (BK-3 has no test; `test_an_upload_that_does_not_read_back_is_refused` asserts only that the exception is raised).
  - "Wrong recovery key" is tested by key-id mismatch (`recovery_key_missing`), not by a wrong key with a forged id. The cryptographic wrong-key case is covered in unit tests only.
  - Alerting delivery; application-secret recovery; an old set after a key rotation in the drill (a unit or integration test exists).
  - That the drill result in `backup_runs` reaches a human.

### 3H. Monitoring, retention and operational readiness

- **Alert logic exists** (`apps/api/markx/ops/checks.py:695-841`): `backup.failed`, `backup.incomplete`, `backup.stale` (no verified **off-site** set within `backup_max_age_hours`), `backup.drill_failed`, `backup.drill_overdue`. The container healthcheck runs `markx.backup check` (`compose.yaml:310-318`).
- **Delivery:**
  - `ops/alerts.py:89-95`: Telegram if a bot token and chat id are set, otherwise **log only**. No alert group exists (F-18 open). **Humans currently receive nothing.**
  - A Docker "unhealthy" status notifies no one.
- **Single point of failure:** the checks run inside the app on the same server and read `backup_runs` in the same database. **Losing the server, the DB, the worker or the scheduler silences every backup alert.** There is no external dead-man's switch (for example a heartbeat to an outside monitor) (**High, BK-4**).
- **Retention** (`B/retention.py`): conservative and well reasoned.
  - The newest `min_sets` complete sets are always kept; nothing is deleted without a complete set; untrusted manifests are never deleted; blobs are kept 48 h grace and only if no kept set needs them; and if any kept set's blob list is unreadable, nothing is deleted.
  - Retention days and minimum sets are required on real environments (founder decision F-20).
  - The blueprint says 30 days (H.2).
- **Other observations:**
  - Every container start runs a full set immediately (`__main__.py:218-222`), so each deploy produces two sets (pre-migration plus start-up). Harmless but noisy.
  - A crash loop under `restart: unless-stopped` would hammer the database and the bucket (Low).
- **Capacity:** no monitoring of bucket size, local `work_dir` disk usage (local sets plus failed evidence), or egress cost.
- **RPO / RTO:**
  - **RPO by design** is up to 24 h (nightly at 23:00 UTC), plus the time to detect a failure (26 h stale threshold), so the **worst case is about 50 h before a stale alert** even if alerts worked. Files changed between sets have no protection (F-14).
  - **RTO is unmeasured.** The 4-hour target is an estimate, with no measurement on real volumes. The CI drill time on demo data is not a meaningful RTO.

### 3I. Verified strengths (backup)

1. A correct, modern, library-backed AEAD streaming format with complete truncation and reorder protection.
2. A public-key design: the server cannot read past backups in normal operation.
3. An Ed25519-signed manifest with a hash chain covering the dump, the index, each file's plaintext hash, counts and status; the set id is bound.
4. A true point-in-time database snapshot, shared by pg_dump, row counts and file references.
5. Database-to-file reference reconciliation, with fail-closed "unclassified" handling.
6. A full read-back of every upload; the manifest written last; atomic local writes.
7. Strict restore targets (new database, empty separate stores, typed confirmation), with verification before any write.
8. No secrets in argv; environment scrubbing for child processes; key-file permission enforcement; `keygen` never overwrites.
9. Conservative retention that keeps everything when in doubt.
10. Honest documentation: DECISIONS and the runbook state clearly what is not connected or proven.
11. Real integration tests against PostgreSQL and MinIO (22 recovery tests) plus a CI drill with fault injection.

---

## 4. Backup threat model

| Attacker / failure | Can read backups? | Can forge or alter? | Can destroy? | Detected? |
|---|---|---|---|---|
| Bucket reader (leaked read key, misconfigured public read) | No (encrypted); manifest metadata visible | — | — | — |
| Bucket writer without the server | No | Substitution or tampering detected at restore or deep verify; **not** by default verify | **Yes** if the key has delete | Stale or failed alerts only if alerting works |
| **Compromised production server** | Past sets: no. **Future data: yes** (it reads the live DB anyway). **During a drill: yes, it captures the recovery key and can then decrypt all history** | **Yes**: holds the signing key and can forge sets, including a malicious dump that executes SQL or shell code as superuser on the recovery host | **Yes**: holds a delete-capable key | Alerts run on the compromised box |
| Lost recovery key | — | — | Effectively all sets lost | Not detected until a restore is attempted |
| Lost signing key | No impact on decryption; `--signer` fallback still needs the public signer key | — | — | — |
| Lost application secrets | Restore succeeds but encrypted columns and signed codes are unusable | — | Partial data loss (staff TOTP) | Not detected by the drill |
| Provider outage or account closure | — | — | All sets unavailable; there is no second destination (the blueprint's weekly drive copy is not automated) | Stale alert (if delivered) |
| Silent bit-rot or blob damage | — | — | Affected files unrecoverable | Only by deep verify or drill (monthly, manual) |

---

## 5. Backup findings and severity

| ID | Severity | Finding | Evidence | Exact fix |
|---|---|---|---|---|
| **BK-1** | **Critical (P0)** | The production server's destination key can delete every backup. No immutability is required, checked or designed. | `destination.py:383-385`; `retention.py:143-157`; `__main__.py:225-231`; runbook step 3 grants `DeleteObject` | (a) **Remove `DeleteObject` from the server's key**: give it Put, Get and List only. (b) Move retention to a separate, off-server, rarely-run job with its own delete key, or use provider lifecycle rules. (c) Require S3 Object Lock in compliance mode with a retention period ≥ the RPO window, or R2 bucket locks (**verify R2 availability**), and have `check_access` verify object-lock or bucket-lock status on real environments and refuse to start otherwise. (d) Make the code version-aware, or rely on lifecycle expiry. |
| **BK-2** | **High (P0 process)** | The monthly drill puts the recovery key on the production server and restores as superuser into the production cluster. | Runbook `:178-197`; `drill.py` docstring "On a server, files are restored into a temporary folder" | Make the drill run **only on a separate disposable recovery host**: a CI-like runner or the operator laptop with its own PostgreSQL 17 container, using the read-only bucket key. Forbid `drill` when `MARKX_ENV` is staging or production on the app host. Update the runbook. This also proves recovery without the server. |
| **BK-3** | **High** | A blob that fails read-back stays at the destination. Later incremental runs reuse it by name only, and sets are marked complete and verified. | `destination.py:339-346` (no delete on mismatch); `runner.py:249-251, 261-263, 280-281` (`blob in remote`, size ignored); test `:568-579` asserts only the raise | On `VerificationFailed`, delete the object and treat it as never uploaded. When reusing, at minimum compare the remote size to the catalog's ciphertext size, and record each blob's ciphertext SHA-256 and size in the index so that verify can check without decrypting. Add a scheduled **deep verify** of the newest set (for example weekly) from off-server. Add a regression test. |
| **BK-4** | **High** | All alerting is on-box, and no channel is configured, so total server loss is silent. Docker unhealthy status notifies no one. | `ops/alerts.py:89-95`; `ops/checks.py:695-841`; F-18 open | An external dead-man's switch: the backup service pings an outside heartbeat URL after each verified set, and the outside service alerts when it is missed. Configure the Telegram alert group **and** a second channel. Prove that a test alert reaches a phone (runbook step 7). |
| **BK-5** | **High** | Application secrets (`MARKX_ENCRYPTION_KEY`, `MARKX_SECRET_KEY`, DB role passwords, TLS keys) are not in the backup and have no escrow procedure, so a total-loss restore yields unusable encrypted columns (staff TOTP) and invalidated codes. | `docs/runbooks/backup-and-restore.md` (no secret escrow); `core/security.py:37` (single `secret_key`) | Add an off-server, encrypted secrets escrow kept with the recovery key (same custody as F-19), document it in the DR runbook, and add a drill step that restores with the escrowed secrets and logs in a staff user with TOTP. |
| **BK-6** | **High** (conditional on server compromise) | Forged sets can execute SQL or shell commands on the recovery host, because restore runs as superuser and the signing key is on the server. | `crypto.py` docstring; runbook `PGUSER=postgres`; `database.py:239-271` | Restore into a **throwaway** PostgreSQL instance (container) with no network and no secrets. Run `pg_restore` as a non-superuser owner role (`--role`, or a dedicated restore role without superuser). Document that sets made after a suspected compromise are untrusted. Optionally move signing to an off-server co-signer, accepting the operational cost. |
| **BK-7** | Medium | Restore or drill on the production cluster can reset production role passwords through bootstrap. | `bootstrap.sh:14-25`; runbook "Always pass the three passwords" | Refuse role creation or reset if roles already exist on the target cluster, unless an explicit `--reset-roles` is given; or always restore on a separate cluster (covered by BK-2). |
| **BK-8** | Medium | Off-site is decided by provider label, not by endpoint. An `s3` endpoint on the same host passes. | `config.py:130-133` | Refuse endpoints resolving to loopback, private or link-local ranges, or to the server's own addresses, on real environments. |
| **BK-9** | Medium | The backup uses the schema-owner role (`markx_migrator`), with internet egress. | `compose.yaml:291-292` | A dedicated `markx_backup` role with `pg_read_all_data`. |
| **BK-10** | Medium | Restore depends on content type sniffed from the first 16 bytes; any future non-image upload would back up but be refused at restore. | `runner.py:241`; `restore.py:384-386` | Store the content type from the source object's `ContentType` or the DB in the index; add a test that enforces "every allowed upload type round-trips". |
| **BK-11** | Medium | There is no scheduled deep verification; default `verify` checks presence only. | `restore.py:263-283` | A weekly off-server `verify --deep`, recorded and alerting. |
| **BK-12** | Medium | Signing-key rotation re-uploads every blob and leaves old sets "untrusted", kept forever. | `crypto.py:155-163`; `__main__.py:174-175` | Derive the blob-name key from a separate stable secret; let retention accept a configured list of trusted signers. |
| BK-13 | Low | The anonymous **read** of objects is not checked at backup time; only anonymous list is. | `destination.py:303-314` | Also call `anonymous_can_read` on the uploaded manifest. |
| BK-14 | Low | `list_multipart_uploads` is not paginated. | `destination.py:391` | Use the paginator. |
| BK-15 | Low | The plaintext manifest leaks schema and per-table row counts (business volume). | `runner.py:462-477` | Move `row_counts` into the encrypted index; keep only totals plus hashes in the manifest. |
| BK-16 | Low | Unexpected exceptions in restore leave the created DB without a FAILED report. | `restore.py:553-564` | Catch broadly after `created=True`; always report. |
| BK-17 | Low | CI drill uses root MinIO keys and a floating `postgres:17` tag. | `ci.yml:117-131` | Least-privilege MinIO users (read-only source, no-delete destination) and pinned `postgres:17.12`. |
| BK-18 | Low | The recovery key is unprotected plaintext base64 with no passphrase or split. | `crypto.py:214-218` | Optionally wrap it with age/scrypt passphrase encryption, or a 2-of-3 Shamir split (founder custody decision F-19). |

## 6. Backup activation readiness

- **Safe to connect to real off-server storage today?** **No.** Fix BK-1 (no delete on the server key, plus immutability) first, then BK-3. BK-2's process must change before the first drill.
- **Safe to trust with real customer data?** **Not yet.** Also required: BK-4 (alerts that work without the server), BK-5 (secret escrow), and one successful restore **on a separate machine** from a real bucket, timed (a measured RTO).
- **Must be fixed or done before activation:**
  - code and process: BK-1, BK-2, BK-3, BK-4, BK-5, BK-6 (restore as non-superuser in a disposable instance);
  - founder decisions F-16 (provider, region, object lock), F-19 (key custody, two locations), F-20 (retention), F-18 (alert channel);
  - one off-server drill, recorded.

---

## 7. Blueprint requirements matrix (summary; 57 rows from sub-review, key rows spot-checked)

| Status | Count | Examples (evidence) |
|---|---|---|
| Implemented and tested (local, fakes or MinIO) | ~30 | OTP sign-in (`t/api/test_auth_otp.py`), sessions and CSRF, staff 2FA (`test_auth_staff.py`), seller onboarding and isolation, offers (one per seller/variant/condition, DB-enforced), atomic stock (`t/db/test_checkout_contention.py`), server-side repricing and idempotency, a DB-enforced order state machine, handover codes, failed delivery, disputes, reviews, reports, search (Amharic, Latin-letter Amharic, typos), outbox, audit log insert-only, i18n parity (1278/1278 keys), backup (MinIO) |
| Implemented, weakly verified | ~4 | Telegram/SMS alerts (fakes only), nightly reconciliation, CI gates, deployment (rehearsal only) |
| Partial | ~14 | Telegram sign-in (API only, no bot or Mini App); guest checkout (phone sign-in first); price history (no chart); address (no gate photo or saved list); dispatch board (no courier link or pickup code); commission engine (**cap stored but never applied**, no rules tool); filters/sorts (no total-to-door sort); privacy requests (recorded, no fulfilment); retention (OTP rows never deleted); seller ownership transfer; quick edit (no bot); legal disclosure (wording pending) |
| Not implemented | ~6 | Ethiopian calendar and clock, lite mode, PWA manifest and Telegram Mini App (CSP `frame-ancestors 'none'`, `next.config.ts:41`), IMEI/serial capture (column unused, `orders/models.py:243`), share cards and QR, yearly seller re-verification |
| Blocked: external | SMS provider, Telegram bot, Turnstile production widget, S3/R2 buckets, CDN, domain/TLS, monitoring, payments, couriers |
| Blocked: founder decision | F-01–F-08 (provisional), F-11–F-20, N-1 (order-alert channel, a launch blocker), O.1–O.25 (data location, legal wording, partners), search golden-query set |
| Defective / contradictory | Commission cap not applied (over-charge risk if any capped rule is created); OTP 24 h deletion not done (G.2); payout cool-off 72 h vs 48 h (H.2); parent "completed" while a part is still in its problem window; payment can only be recorded after handover (blocks recording advance transfers) |

## 8. Backend audit (sub-review; H1 and M6 spot-checked)

- **Solid:**
  - OTP: keyed hash, constant-time compare, row lock, 5-minute expiry, lock after 5 tries.
  - Sessions: 256-bit tokens, hashed, rotated, idle and absolute expiry.
  - CSRF: custom header + Origin/Sec-Fetch-Site + session-bound token + SameSite.
  - Staff: Argon2id + TOTP with replay guard and encrypted secret.
  - Trusted-proxy allowlist; seller isolation through `require_seller` with `seller_id` filters.
  - Stock: a single conditional UPDATE with CHECK constraints and ordered locks.
  - Server-side pricing; handover codes derived and constant-time; signed private links lasting 5 minutes; Pillow re-encoding.
  - Telegram webhook: secret and update-id dedupe. No SSRF surface; CSV-injection guard; outbox `SKIP LOCKED` with savepoints; balanced-ledger trigger; production config refuses dev secrets.
- **Defects:**
  - **H1, spot-checked:** staff conflict-of-interest guard `_refuse_own_seller` (`sellers/service.py:150`) is used only at `:703` and `:839`. It is **absent** from `resolve_dispute` (`orders/service.py:1939`), review moderation, offer takedowns, staff dispatch and handover reissue.
  - **H2:** indefinite stock-hold griefing through cancel-and-reorder from cheap phone accounts (`orders/service.py:763-773, 1088`; no per-offer or per-seller hold cap).
  - **M6, spot-checked:** the overdue job only covers `CONFIRMED` and `READY` (`orders/service.py:1718`), so `out_for_delivery` and `delivery_failed` can hold stock and buyer slots forever.
  - **M5:** fee avoidance by marking an order failed or returned after cash was collected; seller-attested payments only; no staff API for commission rules (`CHANGE_FEES` is unused).
  - **L4:** retention covers only search, rate-limit and Telegram rows; OTP, session, SMS and notification rows are kept forever; data requests are stored but never processed.

## 9. Security audit

No Critical application-security finding was found by the sub-review. The highest risks are backup BK-1/BK-2/BK-6 and staff conflict of interest (H1).

| Severity | Finding | Evidence |
|---|---|---|
| Critical | BK-1: backup destruction from the server | §5 |
| High | BK-2: recovery key on the server during drills; BK-6: superuser restore of forgeable sets | §5 |
| High | H1: staff can decide disputes, moderate and take down offers for stores they belong to or orders they placed | `orders/service.py:1939`, `reviews/service.py:250`, `offers/service.py:594` |
| High | H2: stock-hold denial of service against competitors | `orders/service.py:763-773, 1088` |
| Medium | M2: one global SMS budget of 500/day can be exhausted, blocking all sign-ins | `accounts/service.py:197-205` |
| Medium | M3: targeted lockout of staff (no code needed) and staff-number enumeration (429 vs 401) | `accounts/service.py:539-566` |
| Medium | M4: Telegram init-data replayable for 1 h; no single-use marking | `accounts/service.py:79, 645, 659` |
| Medium | M1: fake reviews through self-orders (pay on delivery costs nothing) | `reviews/service.py:121-126` |
| Medium | CSP `script-src 'unsafe-inline'` weakens XSS defence | `apps/web/next.config.ts:32` |
| Medium | Gitleaks line-level allowlist (`dev[-_]only` anywhere on a line) can hide real secrets | `.gitleaks.toml:15-25` |
| Medium | Secrets passed as environment variables (visible through `docker inspect`); one `secret_key` for all purposes, with no rotation overlap | `api.env.example`; `core/security.py:37` |
| Low | Slow OTP guessing (~20/h per phone); tracking links unrevocable for 60 days; sellers keep buyer PII after completion; upload size checked after the body is spooled; OpenAPI public in production; no `__Host-` cookie prefix; managers can add any phone to a team | sub-review L1–L9 |
| Supply chain | Actions pinned by tag, not SHA; images by tag, not digest; no container scan; no scheduled audit or Dependabot; npm allowlist entry expires 2026-12-31 | `ci.yml`, `compose.yaml`, `.github/security/npm-audit-allowlist.json` |

## 10. Frontend audit (sub-review)

- **Good:**
  - Next 16.4.6 / React 19.3.1.
  - Exact EN/AM key parity (1278 keys, placeholders consistent).
  - Skip link, `lang`, live regions, 48 px targets.
  - No decorative or dead controls found.
  - e2e at 360 px and 1280 px.
- **Defects:**
  - **No `error.tsx` or `global-error.tsx`**: server errors show an unlocalized default page.
  - **Network failures hang the UI.** About 20 client components await `browserApi` or `sendForm` without try/catch; for example `AddToCart.tsx:25-31` stays disabled forever after a network drop. This matters a lot for Ethiopian mobile networks (High for UX).
  - No automated accessibility check (axe).
  - Amharic translation quality is unreviewed by a native editor.
  - e2e runs against `next start`, not the production image behind nginx, and does not run on PRs.
  - Missing: Ethiopian calendar, lite mode, PWA, price-history chart.

## 11. Marketplace business logic

- **Supported (code):** multiple sellers per product with independent price and stock; multi-seller parent and seller orders; cancellations; seller response deadlines with expiry and next-best-offer; failed delivery, retry and return; disputes with staff decisions (no money movement); direct pay-on-delivery recorded by the seller; a ledger with a balance trigger.
- **Incorrect or missing:**
  - Commission cap never applied; no commission-rules management.
  - No refund record (J.5 contradicted).
  - No money-return flow for paid undelivered parts (F-09).
  - Seller settlement and payouts: models only, no routes.
  - Fees avoidable through failed or returned status.
  - Payment is seller-attested only.
  - No buyer cancellation-abuse scoring.
  - Mid-delivery orders never expire.
- **Awaiting the founder:** payment provider (O.20), refund policy and legal wording (O.13), courier partner (O.22), the provisional F-01–F-08 answers, the order-alert channel (N-1). **I invent none of these.**

## 12. Integration status

| Integration | State |
|---|---|
| SMS provider | Adapter plus fake; **no provider** (F-11) |
| Telegram bot and linking | Linking built and **switched off**; no bot, no webhook registered; alerts to fakes only |
| Turnstile | Stand-in only; production widget keys absent |
| Object storage (live files) | S3/R2 adapter; **MinIO only** (F-01) |
| Backup storage | S3/R2 adapter; **MinIO only** (F-16) |
| CDN / media domain | None (F-15) |
| Domain / TLS | None; certificate install script missing; no renewal (F-17) |
| Monitoring / error tracking | None (F-18) |
| Courier / logistics | Manual dispatch board only |
| Payments | **None** ("payment webhooks are not built", `core/http.py:34`) |
| Android app | Not started |

## 13. Infrastructure audit (sub-review)

- **Good:**
  - Non-root containers, `read_only`, `cap_drop: ALL`, `no-new-privileges`.
  - Postgres on an internal network with no host port.
  - Healthchecks everywhere; TLS 1.2/1.3 with ECDHE; HSTS.
  - Unknown hostnames refused at the handshake; gzip off on purpose (BREACH); nginx rate limits; JSON logs with rotation; `deploy.sh check` for file modes and placeholders.
- **Defects:**
  - **Certificate renewal missing** (`docs/runbooks/tls-certificates.md:24-31`): certificates will silently expire.
  - **Rollback hard-codes the image name `markx/`**, ignoring `MARKX_IMAGE_PREFIX` (`deploy.sh:191`), and does not roll back the backup service.
  - A failed post-migration verify leaves the system half-up (`deploy.sh:154-159`).
  - Tags not digests; memory-only limits (no CPU or pids).
  - uid 999 assumed but not fixed in the Dockerfile.
  - Single-copy services, so deploy downtime.
  - No log shipping.
  - Never run on a real server: only the local rehearsal.

## 14. CI and testing audit

- **Verified on GitHub:** CI #131/#132 green on 373c082; CI #129/#130 and journeys #21 green on 937c410.
- **Coverage:** ruff, format, mypy strict, alembic upgrade + `check`, pytest (887 test functions) against real Postgres and MinIO (`MARKX_TEST_*_REQUIRED=1`, so they cannot silently skip), the OpenAPI drift check, web lint/type/vitest/build, gitleaks, pip-audit, an npm audit gate, container builds with non-root checks, a production rehearsal and a backup drill.
- **Gaps:**
  - Journeys do not run on PRs.
  - No scheduled runs or Dependabot.
  - No container image scan.
  - No migration downgrade or upgrade-from-previous-release test.
  - No accessibility test.
  - No load test.
  - No test of BK-3.
  - The drill does not use least-privilege keys.
  - Branch protection or required checks on `main`: **NOT VERIFIED**.

## 15. Release readiness scorecard (estimates, marked as opinion; not percentages of "done")

| Dimension | Rating | Basis |
|---|---|---|
| Code completeness (R1 core loop) | Substantial; about 70–80% of R1 rows built (estimate) | Matrix §7 |
| Backend readiness | Good, with defects H1, H2, M5, M6 | §8 |
| Frontend readiness | Fair: network-error handling and error pages missing | §10 |
| Security readiness | Good application core; backup trust model not yet safe | §5, §9 |
| Infrastructure readiness | Designed and rehearsed locally; **never run on a real server** | §13 |
| Integration readiness | **Low**: no real external service is connected | §12 |
| QA readiness | Strong automated tests; **no real-device, real-network or real-provider testing** | §14 |
| Backup/recovery readiness | Good engineering; **not activatable** until the P0 fixes | §6 |
| Real-world readiness | **Not ready** | Everything external is blocked |
| Staging readiness | Blocked: no server, domain, buckets or SMS; BK-1/BK-2 must be fixed before real data | |
| Production readiness | **Not ready** | All of the above, plus legal and founder decisions |

## 16. All P0 and P1 findings

- **P0:** BK-1 (backup deletion from the server, no immutability); BK-2 (recovery key on the server for drills); BK-3 (damaged blob silently reused); repository state (all code on an unmerged branch; `main` empty).
- **P1:**
  - BK-4 (alerts on-box, no channel); BK-5 (no secret escrow); BK-6 (superuser restore of forgeable sets); BK-7 (role password reset on the production cluster).
  - H1 (staff conflict of interest); H2 (stock-hold griefing); M6 (mid-delivery orders never expire); commission cap not applied.
  - Frontend network-failure hangs plus no error boundary.
  - TLS renewal missing; rollback image-prefix bug.
  - SMS budget DoS (M2); staff lockout and enumeration (M3); Telegram replay (M4).
  - OTP/PII retention gaps (L4 + G.2); data-request fulfilment missing.

## 17. Prioritized implementation roadmap (safest order)

Each task lists: priority · why · defect · evidence · implementation · dependencies · founder input · external cost · acceptance.

### P0 (critical)

1. **Consolidate the repository source of truth.**
   - Priority: P0. Why: all code sits on one unmerged branch.
   - Implementation: the founder reviews PR #1; merge to `main`; enable branch protection with the CI checks required; archive or reconcile the two divergent `claude/*` branches.
   - Founder input: yes (merge approval). Cost: none.
   - Acceptance: `main` == reviewed HEAD; protection rules active.
2. **BK-1: no-delete server key plus immutable destination.**
   - Implementation: split credentials (server: Put/Get/List; retention: a separate off-server key or provider lifecycle); add a `check_access` object-lock/bucket-lock assertion on real environments; version-aware retention, or lifecycle-based retention; tests with a MinIO object-lock bucket.
   - Dependencies: none in code; the F-16 provider choice decides lock semantics.
   - Founder input: confirm that object lock is acceptable (cost). Cost: the storage for the lock window.
   - Acceptance: a server key cannot delete any object (test); the service refuses a bucket without a lock on staging and production; the MinIO object-lock test passes.
3. **BK-3: verification-failure cleanup and reuse verification.**
   - Implementation: delete on mismatch; size and ciphertext-hash check on reuse; record the ciphertext hash in the index; regression test.
   - Founder input: no. Cost: none.
   - Acceptance: a new test (damage a blob after a failed read-back; the next run re-uploads it) passes.
4. **BK-2 / BK-6: off-server drill and safe restore.**
   - Implementation: `drill` and `restore` refuse to run on a host with `MARKX_ENV` staging or production; a documented disposable recovery-host procedure (a Docker PG17 container, a non-superuser restore role, the read-only bucket key); runbook rewrite.
   - Founder input: no (F-19 custody later). Cost: none.
   - Acceptance: the drill runs end to end on a clean machine with no server access; the server refuses `drill`.

### P1 (launch blockers)

5. **BK-5: secrets escrow and DR runbook.** Founder input: yes (custody, F-19). Acceptance: a restore on a clean host signs in a staff user with TOTP.
6. **BK-4: external heartbeat plus a two-channel alert route.** Needs F-18 (a free tier exists for several monitors; small cost). Acceptance: killing the server triggers an outside alert within N hours; a test alert reaches a phone.
7. **Staff conflict-of-interest guard (H1).** Apply `_refuse_own_seller` and an "own order" check to disputes, moderation, takedowns, dispatch and reissue; add tests. Founder input: no.
8. **Order-lifecycle hardening.** Expiry or escalation for `out_for_delivery` and `delivery_failed` (M6); per-offer and per-seller stock-hold caps plus a cancel-and-reorder cooldown (H2); apply the commission cap or refuse capped rules. Founder input: the timeout values.
9. **Frontend resilience.** A shared fetch wrapper with try/catch and retry UI; `error.tsx` and `global-error.tsx` in both locales; an e2e offline test.
10. **Auth abuse controls.** Per-network SMS budget slices or a per-prefix quota (M2); staff lockout per IP plus a uniform 401 (M3); single-use Telegram init data and a shorter max age (M4).
11. **Infrastructure fixes.** The certificate install and renewal hook; the rollback prefix and backup-service rollback; digest pinning; SHA-pinned Actions; a container scan; journeys on PRs; a scheduled weekly CI run.
12. **Privacy and retention.** OTP deletion after 24 h; session, SMS and notification retention per F-08/O.19; a staff workflow for data requests. Founder input: the retention periods.
13. **Activate external services, in order:** F-16 backup bucket (after 2–6) → F-01 file buckets → F-17 domain/TLS → F-11 SMS → Turnstile → F-18 monitoring → Telegram bot (N-1) → staging deploy → the first off-server drill with a measured RTO. All need the founder and cost money.

### P2 (Release 1 completion)

Telegram sign-in UI and Mini App (CSP framing allowance); refund records and the paid-undelivered money-return flow (F-09); commission-rules admin tool; settlement and payout routes; dispatch courier link and pickup code; price-history chart; saved addresses and gate photo; total-to-door sort; IMEI capture; Ethiopian calendar; lite mode and PWA; share cards and QR; seller ownership transfer; yearly re-verification; review photos; native Amharic review; axe in e2e.

### P3 (improvements)

Zero-downtime deploys; log shipping; load tests; CPU and pids limits; a re-encryption tool for old backups; a second backup destination (the blueprint's weekly drive copy); passphrase or Shamir protection for the recovery key (BK-18); moving row counts out of the plaintext manifest (BK-15); a stricter CSP with nonces.

## 18. Founder decisions required

F-01–F-08 (confirm the provisional answers), F-09 refunds, F-11 SMS provider, F-12/F-13 SMS records and budget unit, F-14 versioning of the live buckets, F-15 media domain, **F-16 backup provider, region and object lock**, F-17 domain/TLS/Cloudflare, **F-18 alert channel and monitor**, **F-19 recovery-key and secret custody**, **F-20 backup retention** (the blueprint says 30 days), N-1 order-alert channel, O.1 data location, O.13 legal disclosure and returns wording, O.19 retention periods, O.20 payment provider, O.22 couriers, the search golden set, and merging PR #1.

## 19. External services and costs eventually required

- S3 or R2 for the live buckets and the backup bucket (with object lock).
- A CDN and media domain; a domain registrar and DNS; Let's Encrypt (free).
- An Ethiopian SMS gateway; Cloudflare Turnstile (free tier).
- A Telegram bot (free).
- An uptime monitor and heartbeat service, plus error tracking (free or low-cost tiers exist).
- A VPS or cloud server (staging and production).
- A disposable recovery host or CI runner for drills (can be free CI).
- Later: a payment provider (Chapa or similar), a courier API, Fayda ID checks.

**Specific prices are NOT VERIFIED.**

## 20. Safe to build next without external infrastructure

BK-1 (code side plus a MinIO object-lock test), BK-3, BK-2/BK-6 (refusal plus a recovery-host procedure in a local container), BK-7, BK-8, BK-9, BK-10, BK-11, the heartbeat client (BK-4 code side, URL configurable), H1, H2, M6, the commission cap, frontend error handling and boundaries, the auth abuse controls, retention jobs, the infra and CI fixes (excluding the real certificate), and all P2 UI work. All of this can be tested in CI with Postgres and MinIO.

## 21. What is NOT verified

- Anything against real AWS S3 or Cloudflare R2, including R2 checksum, ETag and bucket-lock behaviour with boto3 1.44.
- A restore on a separate machine.
- RTO and RPO on real volumes.
- Alert delivery to a human.
- Production server deployment, TLS issuance and renewal, real SMS or Telegram, real-device mobile UX.
- Amharic quality.
- Branch protection settings.
- I did not run any tests locally; CI results were read from GitHub.
- Sub-review findings other than H1 and M6 were not independently re-read line by line.
- The test suite's assertions were sampled, not exhaustively reviewed.
- Performance targets (300 ms search) are unmeasured.

## 22. Final recommendation

- **The safest and most valuable next task: the "Backup trust hardening" milestone, BK-1 + BK-3 + BK-2/BK-6, done together, preceded by merging the reviewed PR #1 into a protected `main`.**
- **Why:**
  1. It is the only work that closes a **data-loss** path: a compromised or misconfigured server could erase every backup, and a damaged copy could be silently reused as "verified".
  2. It is the gate for activating the first external service (F-16). Every later step, including staging with real data, depends on having a recovery point that the server cannot destroy and that has been proven on another machine.
  3. It needs **no external service, cost or founder decision** to build and test (MinIO supports object lock). Founder decisions F-16, F-19 and F-20 can be made in parallel.
  4. The changes are small and local to `apps/api/markx/backup/*`, the runbook and the tests. They are low-risk to existing marketplace functionality.
- **Then:** BK-4/BK-5 (alerts and secret escrow), then H1 and the order-lifecycle fixes, then frontend resilience, then external activation in the order given in §17.13.

*No implementation will start until the founder approves.*

---

### After approval (execution note)

Plan mode allowed writing only this file. If approved, the only follow-up action proposed is to copy this report unchanged to the session scratchpad (`/tmp/claude-0/-home-user-markx-marketplace/7d1a7e34-d7c4-53b1-b4b7-a2aca92d8613/scratchpad/MARKX_AUDIT_2026-11-19.md`). Nothing will be committed or pushed and no code will be changed. Any fix work will be proposed separately.
