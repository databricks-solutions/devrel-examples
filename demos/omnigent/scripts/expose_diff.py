#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
DEMO = ROOT / "demos" / "omnigent"
CLIENT_ROOT = "demos/omnigent/issue-triage/"
BASE_FILE = DEMO / ".demo-base"
BRANCH_FILE = DEMO / ".demo-branch"
PAGINATION_BRANCH = "feat/ghlite-pagination"
FINAL_BRANCH = "feat/ghlite-filter-prs"


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=ROOT, check=check, text=True, capture_output=True)


def refuse(message: str) -> None:
    print(f"REFUSED: {message}", file=sys.stderr)
    raise SystemExit(1)


def require_commit(ref: str) -> str:
    result = run("git", "rev-parse", "--verify", f"{ref}^{{commit}}", check=False)
    if result.returncode:
        refuse(f"missing required branch or commit: {ref}")
    return result.stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Expose Polly's combined result in Omnigent Changes")
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()

    if not args.yes:
        refuse("pass --yes to approve the local fast-forward and mixed reset")
    if not BASE_FILE.is_file() or not BRANCH_FILE.is_file():
        refuse("setup did not record the starting branch and commit")

    base_sha = require_commit(BASE_FILE.read_text().strip())
    starting_branch = BRANCH_FILE.read_text().strip()
    current_branch = run("git", "branch", "--show-current").stdout.strip()
    if current_branch != starting_branch:
        refuse(f"expected starting branch {starting_branch!r}, found {current_branch!r}")
    if require_commit("HEAD") != base_sha:
        refuse("starting branch moved since setup")
    if run("git", "status", "--porcelain").stdout.strip():
        refuse("starting checkout has modified or untracked files")

    pagination_sha = require_commit(PAGINATION_BRANCH)
    final_sha = require_commit(FINAL_BRANCH)
    if run("git", "merge-base", "--is-ancestor", pagination_sha, final_sha, check=False).returncode:
        refuse(f"{FINAL_BRANCH} is not based on {PAGINATION_BRANCH}")
    if run("git", "merge-base", "--is-ancestor", base_sha, final_sha, check=False).returncode:
        refuse(f"{FINAL_BRANCH} cannot fast-forward the recorded starting commit")

    changed = run("git", "diff", "--name-only", f"{base_sha}...{final_sha}").stdout.splitlines()
    if not changed:
        refuse("final branch contains no changes")
    outside = [path for path in changed if not path.startswith(CLIENT_ROOT)]
    if outside:
        refuse(f"final branch changes files outside {CLIENT_ROOT}: {outside}")

    print(f"Fast-forwarding {starting_branch} to {FINAL_BRANCH} ({final_sha[:12]})")
    run("git", "merge", "--ff-only", FINAL_BRANCH)

    python = DEMO / "issue-triage" / ".venv" / "bin" / "python"
    tests = subprocess.run(
        [str(python), "-m", "pytest", "-q"], cwd=DEMO / "issue-triage"
    )

    # Whether tests pass or fail, restore the branch pointer while retaining the
    # combined content as a working-tree diff for inspection and safe reset.
    run("git", "reset", "--mixed", base_sha)
    print(run("git", "status", "--short").stdout, end="")

    if tests.returncode:
        print("NOT READY: combined tests failed; use the completed rehearsal session", file=sys.stderr)
        raise SystemExit(tests.returncode)
    print("READY: combined tests pass and Changes can display the working-tree diff")


if __name__ == "__main__":
    main()
