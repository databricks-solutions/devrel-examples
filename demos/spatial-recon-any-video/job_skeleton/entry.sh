#!/usr/bin/env bash
# AIR (serverless GPU) entry: install what the base environment lacks, inside the job, then run.
# Don't pin packages the environment already ships (torch, numpy, opencv, ...): pins force slow downgrades
# before your code starts. Install only what's missing, and log how long each install takes.
set -euo pipefail
echo "JOB_START $(date +%T)"   # first line of output: separates platform start-up from your own setup time
SCRATCH=/local_disk0; [ -w "$SCRATCH" ] || SCRATCH=/tmp
TOOLS="$SCRATCH/tools"; mkdir -p "$TOOLS"
# micromamba + conda-forge COLMAP 4.0.4 CUDA build (pinned by build string and checksum for reproducibility).
MM_URL=https://api.anaconda.org/download/conda-forge/micromamba/2.9.0/linux-64/micromamba-2.9.0-0.tar.bz2
MM_SHA=8761c382127e6363bd9e0a2451aa3ef90d071a79133f736e2f759a3bf13040dd
t=$SECONDS
curl -fsSL "$MM_URL" -o "$TOOLS/mm.tar.bz2"
echo "$MM_SHA  $TOOLS/mm.tar.bz2" | sha256sum -c -
tar -xjf "$TOOLS/mm.tar.bz2" -C "$TOOLS" bin/micromamba
"$TOOLS/bin/micromamba" create -y -q -p "$TOOLS/colmap" -c conda-forge "colmap=4.0.4=cuda_129hdbc9e7e_0"
echo "setup: colmap installed in $((SECONDS - t)) s"
export COLMAP="$TOOLS/colmap/bin/colmap"
exec python "$CODE_SOURCE_PATH/recon_job.py" "$@"
