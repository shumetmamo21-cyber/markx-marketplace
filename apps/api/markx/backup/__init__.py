"""Off-server backup and disaster recovery for MarkX (D-094).

A *backup set* is one PostgreSQL dump and one copy of every stored file,
taken together and described by a signed manifest:

    <prefix>/sets/<backup id>/database.dump.mxb   the pg_dump, encrypted
    <prefix>/sets/<backup id>/files.index.mxb     which file is which blob, encrypted
    <prefix>/sets/<backup id>/blobs.txt           the blob ids the set needs (opaque)
    <prefix>/sets/<backup id>/manifest.json       written LAST, signed: the commit point
    <prefix>/objects/<id[:2]>/<id>                one encrypted blob per distinct file

Nothing is a recovery point until its manifest exists, its signature checks
and its status is `complete`. The pieces:

- `crypto`       keys, the MXB2 encryption format, manifest signatures
- `config`       the backup service's own settings (never the API's)
- `destination`  where sets go: an S3-compatible bucket, or a folder on a laptop
- `sources`      where the stored files are read from (read-only)
- `database`     pg_dump and pg_restore, run without a password on any command line
- `references`   what the database says must exist: file keys and row counts
- `runner`       one backup: lock, snapshot, dump, files, upload, verify, manifest
- `restore`      a set into a NEW database and EMPTY file stores, verified
- `retention`    which sets and blobs may go, and never the last good one
- `records`      each attempt's outcome in `backup_runs`, for the worker's watch
- `drill`        the automated recovery drill, with failure injection
- `__main__`     the command line: keygen, run, serve, verify, restore, drill, prune

Read docs/runbooks/backup-and-restore.md before using any of it on a server.
"""
