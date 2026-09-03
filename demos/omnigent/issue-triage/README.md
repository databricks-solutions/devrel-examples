# ghlite — Omnigent issue-triage demo

> This public code example is intentionally naive. It is local worktree input for the Omnigent conference demo; see [`PILOT.md`](PILOT.md) before changing it.

A thin GitHub REST client I threw together to triage a repo's open issues —
pull them, count them, group them by label. Zero frills on purpose: one
`requests.Session`, a `get()` helper, a function per resource.

It worked fine on a small repo. I'm now pointing it at a real, active tracker
(`omnigent-ai/omnigent`, hundreds of open issues and PRs), and the corners it
cuts start to matter.

## Usage

```bash
./scripts/setup.sh
.venv/bin/python -m ghlite.digest omnigent-ai/omnigent
```

Set `GITHUB_TOKEN` in the environment to use an authenticated rate limit
(5,000/hr instead of 60/hr).

## Known limitations (haven't needed these yet)

These were fine at small scale. Against a big tracker they aren't:

- **No pagination.** `list_open_issues` returns whatever fits on the first page
  (~30 items). On a repo with hundreds of open issues, the triage silently runs
  on the first page only.
- **`/issues` returns pull requests too.** GitHub models PRs as issues, so the
  list is a mix unless you filter on the `pull_request` key.
- **No retry / backoff.** A `403` (rate limit) or a transient `5xx` raises and
  aborts the whole run.
- **No caching.** Every run re-downloads everything, spending rate-limit budget
  on data that hasn't changed.

## Layout

```
ghlite/
  client.py   base client: session, auth, get()
  repos.py    repo metadata
  issues.py   issue listing
  search.py   search wrapper
  digest.py   runnable triage: .venv/bin/python -m ghlite.digest <owner/repo>
```
