#!/usr/bin/env bash
# AIR (serverless GPU) entry: install what the base environment lacks, inside the job, then run.
# Don't pin packages the environment already ships (torch, numpy, opencv, ...): pins force slow downgrades
# before your code starts. Install only what's missing, pinned, and log how long it takes.
set -euo pipefail
echo "JOB_START $(date +%T)"   # first line of output: separates platform start-up from your own setup time
t=$SECONDS
# Pi3X's code, pinned to a commit (the weights are pinned by revision in recon4d_job.py)
PI3_COMMIT=9fa3ddb3f8d53041f8b2738df404f62223bbaa7b
python -m pip install -q --no-input --no-deps "pi3 @ https://github.com/yyfz/Pi3/archive/${PI3_COMMIT}.tar.gz"
need() { python -c "import $1" 2>/dev/null || { echo "setup: installing $2"; python -m pip install -q --no-input "$2"; }; }
need safetensors safetensors==0.6.2
need huggingface_hub huggingface_hub==0.36.0
need pyarrow pyarrow==21.0.0
need scipy scipy==1.15.3
need cv2 opencv-python-headless==4.12.0.88
python -c "import torch, pi3.models.pi3x; print('setup: torch', torch.__version__, 'cuda', torch.cuda.is_available())"
echo "setup: done in $((SECONDS - t)) s"
export HF_HUB_DISABLE_TELEMETRY=1
exec python "$CODE_SOURCE_PATH/recon4d_job.py" "$@"
