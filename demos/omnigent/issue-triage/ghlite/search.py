def search_issues(client, query):
    """Search issues and pull requests with a GitHub search ``query``."""
    return client.get("/search/issues", q=query)
