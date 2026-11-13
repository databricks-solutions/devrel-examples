# 4D reconstruction from a few moving cameras, on Databricks

An agent skill and a job skeleton for turning 2 or more synchronised, moving cameras (drones, phones, robots) into a 4D point cloud of a moving person, on Databricks serverless GPU (AI Runtime).

It is the method behind [drone-swarm-4d](../drone-swarm-4d/): three small drones, one person, 300 slices of 4D, and the public dataset [`nick-karpov/drone-swarm-4d`](https://huggingface.co/datasets/nick-karpov/drone-swarm-4d). It also carries the AIR lessons from the 445 GPU jobs behind it: one job per independent unit, progress and ETA through MLflow with an explicit run id, smoke tests through the real entrypoint, hard exits and cached data prep.

| Path | What it is |
|---|---|
| `SKILL.md` | The recipe: sync, masks, camera tracks, per-instant Pi3X, merge and smoothing, colour, QA, camera count, and running it all on AIR |
| `job_skeleton/recon4d_job.py` | Clip driver: per-slice Pi3X with known poses, Sim(3), temporal smoothing, fusion, clouds; shardable over independent jobs |
| `job_skeleton/pi3x_instant.py` | One instant; `--model stub` tests everything without a GPU |
| `job_skeleton/entry.sh`, `job.yaml` | The AIR job |

To use it as a skill, copy this folder to `.claude/skills/multiview-4d-on-databricks/` in your project, or to `~/.claude/skills/`. For other agents, add `SKILL.md` as a skill or instructions file.

Quick local check, on the synthetic fixture from drone-swarm-4d:

```bash
python ../drone-swarm-4d/tests/make_fixture.py /tmp/fx
cd job_skeleton && python recon4d_job.py --release /tmp/fx --clip clip1_three_drones --out /tmp/r4d --model stub --device cpu
```
