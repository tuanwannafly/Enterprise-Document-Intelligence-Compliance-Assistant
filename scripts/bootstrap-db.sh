#!/usr/bin/env bash
# Bootstrap a fresh Postgres instance with the EDI compliance roles and DB.
# Usage: PGPASSWORD=edi_owner psql -U edi_owner -d edi -h <host> -f scripts/bootstrap-db.sh
set -euo pipefail
HERE="$(dirname "$0")/.."
psql -v ON_ERROR_STOP=1 "$@" -f "$HERE/backend/app/db/bootstrap.sql"
echo "Bootstrap complete. Run migrations next:"
echo "  PYTHONPATH=backend alembic upgrade head"
