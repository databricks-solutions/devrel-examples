#!/usr/bin/env bash
# Apply docs/delta-views.sql against the daniel_liden.casino_floor schema.
# Splits the file into individual statements and submits each to the Statement
# Execution API.
#
# Usage:
#   PROFILE=shared WAREHOUSE_ID=dc68bc2ae6da905b ./scripts/apply-delta-views.sh

set -euo pipefail

PROFILE="${PROFILE:-shared}"
WAREHOUSE_ID="${WAREHOUSE_ID:-dc68bc2ae6da905b}"
CATALOG="${CATALOG:-daniel_liden}"
SCHEMA="${SCHEMA:-casino_floor}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SQL_FILE="$ROOT/docs/delta-views.sql"

# Use Python to split the file by trailing `;` while ignoring `;` inside
# strings/comments, then iterate.
python3 - "$SQL_FILE" "$PROFILE" "$WAREHOUSE_ID" "$CATALOG" "$SCHEMA" <<'PY'
import json
import os
import re
import subprocess
import sys

sql_path, profile, warehouse_id, catalog, schema = sys.argv[1:6]

with open(sql_path) as f:
    src = f.read()

# Strip line comments (only when they start at column 0 or after whitespace,
# never inside a string literal) and split on top-level semicolons.
def strip_and_split(src: str) -> list[str]:
    out: list[str] = []
    buf: list[str] = []
    in_str = False
    i = 0
    n = len(src)
    while i < n:
        ch = src[i]
        if in_str:
            buf.append(ch)
            if ch == "'":
                # SQL escapes single quote by doubling.
                if i + 1 < n and src[i+1] == "'":
                    buf.append(src[i+1])
                    i += 2
                    continue
                in_str = False
            i += 1
            continue
        # Line comment outside string: skip to newline.
        if ch == '-' and i + 1 < n and src[i+1] == '-':
            while i < n and src[i] != '\n':
                i += 1
            continue
        if ch == "'":
            in_str = True
            buf.append(ch)
            i += 1
            continue
        if ch == ';':
            stmt = ''.join(buf).strip()
            if stmt:
                out.append(stmt)
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    tail = ''.join(buf).strip()
    if tail:
        out.append(tail)
    return out

statements = strip_and_split(src)
print(f'Found {len(statements)} statements')

failures = 0
for idx, stmt in enumerate(statements):
    head = stmt.split('\n', 1)[0][:60]
    payload = json.dumps({
        'warehouse_id': warehouse_id,
        'catalog': catalog,
        'schema': schema,
        'statement': stmt,
        'wait_timeout': '50s',
    })
    result = subprocess.run(
        ['databricks', 'api', 'post', '/api/2.0/sql/statements',
         '--profile', profile, '--json', payload],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f'  [{idx+1}] {head} ... CLI ERROR: {result.stderr[:200]}')
        failures += 1
        continue
    response = json.loads(result.stdout)
    state = response.get('status', {}).get('state')
    if state == 'SUCCEEDED':
        print(f'  [{idx+1}] {head} ... ok')
    else:
        err = response.get('status', {}).get('error', {}).get('message', '?')
        print(f'  [{idx+1}] {head} ... {state}')
        print(f'        {err[:300]}')
        failures += 1

if failures:
    print(f'\n❌ {failures} statement(s) failed')
    sys.exit(1)
else:
    print(f'\n✅ all {len(statements)} statements applied')
PY
