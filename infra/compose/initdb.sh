#!/usr/bin/env bash
# Runs once, inside the postgres container, when its data volume is empty:
# creates the three MarkX roles and the `markx` database (D-058). The roles'
# passwords are the laptop defaults of infra/postgres/bootstrap.sh unless
# MARKX_DB_*_PASSWORD are set for the container.
set -euo pipefail
/markx-bootstrap/bootstrap.sh markx
