"""Run src/load_release.py locally with PySpark against a release folder (the fixture or the real release).

    python tests/run_load_local.py RELEASE_DIR [--hf]

Stands in for Databricks: a local SparkSession, a dbutils stub with the job's widgets, and a temporary folder in
place of /Volumes. With --hf, huggingface_hub.snapshot_download is replaced by a copy of RELEASE_DIR, to run the
download path; without it, the job runs with source_dir=RELEASE_DIR. Prints each table's schema, comments and rows.
"""
import shutil
import sys
import tempfile
import types
from pathlib import Path

import os

os.environ.setdefault("PYSPARK_PYTHON", sys.executable)
from pyspark.sql import SparkSession  # noqa: E402

release = Path(sys.argv[1]).expanduser().resolve()
use_hf = "--hf" in sys.argv
work = Path(tempfile.mkdtemp(prefix="drone4d_load_"))
spark = (SparkSession.builder.master("local[2]").appName("load_release_test")
         .config("spark.sql.warehouse.dir", str(work / "warehouse")).config("spark.ui.enabled", "false").getOrCreate())
spark.sparkContext.setLogLevel("ERROR")
spark.sql("CREATE DATABASE IF NOT EXISTS drone_swarm_4d")

widgets = dict(catalog="spark_catalog", schema="drone_swarm_4d", volume="release_files",
               hf_repo="nick-karpov/drone-swarm-4d", hf_revision="main", source_dir="" if use_hf else str(release))
dbutils = types.SimpleNamespace(widgets=types.SimpleNamespace(get=lambda k: widgets[k]),
                                library=types.SimpleNamespace(restartPython=lambda: None))
if use_hf:
    import huggingface_hub

    def fake_snapshot(repo_id, repo_type=None, revision=None, local_dir=None, token=None, **kw):
        assert repo_type == "dataset" and token is False, (repo_type, token)
        shutil.copytree(release, local_dir, dirs_exist_ok=True)
        (Path(local_dir) / ".cache").mkdir(exist_ok=True)
        return local_dir
    huggingface_hub.snapshot_download = fake_snapshot

src = (Path(__file__).resolve().parents[1] / "src" / "load_release.py").read_text()
src = src.replace('"/Volumes/', f'"{work}/Volumes/').replace("f\"/Volumes/", f"f\"{work}/Volumes/")
exec(compile(src, "load_release.py", "exec"), dict(dbutils=dbutils, spark=spark, __name__="__main__"))

for t in ["clips", "frames", "telemetry", "controls"]:
    print(f"\n== {t}: {spark.table(t).count()} rows")
    print(spark.sql(f"DESCRIBE TABLE EXTENDED {t}").where("col_name = 'Comment'").collect()[0][1][:160])
    for r in spark.sql(f"DESCRIBE TABLE {t}").collect():
        if r.col_name and not r.col_name.startswith("#"):
            print(f"  {r.col_name:28s} {r.data_type[:40]:40s} {(r.comment or '')[:90]}")
spark.table("frames").show(3, truncate=60)
spark.table("controls").show(3, truncate=40)
if "detections_detections" in spark.table("controls").columns:
    spark.sql("SELECT clip_id, count(*) AS n, sum(size(detections_detections)) AS dets FROM controls "
              "WHERE stream = 'detections' GROUP BY clip_id").show()
shutil.rmtree(work)
