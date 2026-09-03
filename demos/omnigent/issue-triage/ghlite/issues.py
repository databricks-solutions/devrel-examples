def list_open_issues(client, repo):
    """Return the open issues for ``owner/repo``."""
    return client.get(f"/repos/{repo}/issues", state="open")
