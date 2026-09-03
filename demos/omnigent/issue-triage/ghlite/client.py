import os

import requests

BASE_URL = "https://api.github.com"


class GitHubClient:
    """A minimal GitHub REST client.

    One session, one get() helper. No pagination, retry, or caching — those get
    added when they're actually needed.
    """

    def __init__(self, token=None):
        self.session = requests.Session()
        self.session.headers.update(
            {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        )
        token = token or os.environ.get("GITHUB_TOKEN")
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"

    def get(self, path, **params):
        """GET a single response body from the API and return the parsed JSON."""
        resp = self.session.get(f"{BASE_URL}{path}", params=params)
        resp.raise_for_status()
        return resp.json()
