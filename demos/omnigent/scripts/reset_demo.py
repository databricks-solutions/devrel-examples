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
TASK_BRANCHES = {"feat/ghlite-pagination", "feat/ghlite-filter-prs"}
BASE_FILE = DEMO / ".demo-base"
BRANCH_FILE = DEMO / ".demo-branch"


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
    if not BASE_FILE.is_file() or not BRANCH_FILE.is_file():
        refuse("setup did not record the starting branch and commit")
    base_sha = BASE_FILE.read_text().strip()
    starting_branch = BRANCH_FILE.read_text().strip()
    branch = run("git", "branch", "--show-current").stdout.strip()
    if not branch or branch != starting_branch:
        refuse(f"run reset from recorded starting branch {starting_branch!r}, not {branch!r}")
    if subprocess.run(
        ["git", "cat-file", "-e", f"{base_sha}^{{commit}}"], cwd=ROOT, capture_output=True
    ).returncode:
        refuse("recorded starting commit is not available")
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

    print(f"Restoring {starting_branch} to {base_sha[:12]}")
    run("git", "reset", "--hard", base_sha)

    branches = run("git", "for-each-ref", "--format=%(refname:short)", "refs/heads/").stdout.splitlines()
    for task_branch in branches:
        if task_branch in TASK_BRANCHES or task_branch.startswith(BRANCH_PREFIXES):
            print(f"Deleting branch {task_branch}")
            run("git", "branch", "-D", task_branch)

    for path in (
        ROOT / ".polly",
        DEMO / ".local-polly",
        ROOT / ".worktrees",
        BASE_FILE,
        BRANCH_FILE,
    ):
        if path.exists():
            shutil.rmtree(path)

    python = DEMO / "issue-triage" / ".venv" / "bin" / "python"
    tests = subprocess.run([str(python), "-m", "pytest", "-q"], cwd=DEMO / "issue-triage")
    if tests.returncode:
        refuse("seed tests failed after cleanup")
    if run("git", "status", "--porcelain", "--untracked-files=no").stdout.strip():
        refuse("starting checkout is not clean after cleanup")
    print("READY: starting branch restored; no local task branches/worktrees/artifacts; seed tests pass")


if __name__ == "__main__":
    main()
