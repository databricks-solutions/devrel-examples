def get_repo(client, repo):
    """Return the repository object for ``owner/repo``."""
    return client.get(f"/repos/{repo}")


def list_org_repos(client, org):
    """Return the repositories for an organization."""
    return client.get(f"/orgs/{org}/repos", per_page=100)
