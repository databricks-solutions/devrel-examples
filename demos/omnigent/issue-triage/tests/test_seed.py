from __future__ import annotations

from ghlite.client import GitHubClient
from ghlite.issues import list_open_issues


def test_client_is_anonymous_without_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    client = GitHubClient()
    assert "Authorization" not in client.session.headers


def test_client_uses_environment_token_without_exposing_it(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "example-secret")
    client = GitHubClient()
    assert client.session.headers["Authorization"] == "Bearer example-secret"


def test_small_repository_behavior_that_originally_looked_correct():
    expected = [
        {"number": 1, "title": "First issue", "labels": [{"name": "bug"}]},
        {"number": 2, "title": "Second issue", "labels": []},
    ]

    class SmallRepoClient:
        def get(self, path, **params):
            assert path == "/repos/example/small/issues"
            assert params == {"state": "open"}
            return expected

    assert list_open_issues(SmallRepoClient(), "example/small") == expected
