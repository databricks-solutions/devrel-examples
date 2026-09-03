#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
DEMO = ROOT / "demos" / "omnigent"
WORKTREE_ROOT = (ROOT / ".worktrees").resolve()
BRANCH_PREFIXES = ("polly/", "local-polly/")


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=ROOT, check=True, text=True, capture_output=True)


def refuse(message: str) -> None:
    print(f"REFUSED: {message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset local Omnigent demo worktrees")
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()

    if not args.yes:
        refuse("pass --yes after confirming this is the demo checkout")
    branch = run("git", "branch", "--show-current").stdout.strip()
    if not branch or branch.startswith(BRANCH_PREFIXES):
        refuse("run reset from the starting demo checkout, not a task worktree")
    origin = run("git", "remote", "get-url", "origin").stdout.strip()
    expected = {
        "https://github.com/databricks-solutions/devrel-examples",
        "https://github.com/databricks-solutions/devrel-examples.git",
    }
    if origin not in expected:
        refuse(f"unexpected origin: {origin}")
    if run("git", "status", "--porcelain", "--untracked-files=no").stdout.strip():
        refuse("starting checkout has tracked modifications; inspect them before reset")

    entries = run("git", "worktree", "list", "--porcelain").stdout.splitlines()
    worktrees = [Path(line.removeprefix("worktree ")).resolve() for line in entries if line.startswith("worktree ")]
    for path in worktrees:
        if path == ROOT.resolve():
            continue
        if path != WORKTREE_ROOT and WORKTREE_ROOT not in path.parents:
            refuse(f"worktree is outside {WORKTREE_ROOT}: {path}")
        print(f"Removing worktree {path}")
        run("git", "worktree", "remove", "--force", str(path))
    run("git", "worktree", "prune")

    branches = run("git", "for-each-ref", "--format=%(refname:short)", "refs/heads/").stdout.splitlines()
    for task_branch in branches:
        if task_branch.startswith(BRANCH_PREFIXES):
            print(f"Deleting branch {task_branch}")
            run("git", "branch", "-D", task_branch)

    for path in (ROOT / ".polly", DEMO / ".local-polly", ROOT / ".worktrees"):
        if path.exists():
            shutil.rmtree(path)

    python = DEMO / "issue-triage" / ".venv" / "bin" / "python"
    tests = subprocess.run([str(python), "-m", "pytest", "-q"], cwd=DEMO / "issue-triage")
    if tests.returncode:
        refuse("seed tests failed after cleanup")
    if run("git", "status", "--porcelain", "--untracked-files=no").stdout.strip():
        refuse("starting checkout is not clean after cleanup")
    print("READY: no local task branches/worktrees/artifacts, seed tests pass")


if __name__ == "__main__":
    main()
