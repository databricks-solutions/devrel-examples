"""Triage a repo's open issues: count them and group them by label.

    python -m ghlite.digest omnigent-ai/omnigent
"""

import sys
from collections import Counter

from ghlite.client import GitHubClient
from ghlite.issues import list_open_issues


def main(repo):
    client = GitHubClient()
    issues = list_open_issues(client, repo)

    print(f"Open issues in {repo}: {len(issues)}")

    labels = Counter(label["name"] for issue in issues for label in issue.get("labels", []))
    if labels:
        print("Top labels:")
        for name, count in labels.most_common(10):
            print(f"  {count:3d}  {name}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "omnigent-ai/omnigent")
