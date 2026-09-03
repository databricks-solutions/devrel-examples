# Omnigent booth demo — presenter guide

> Draft for rehearsal. This is a presenter-led, modular demo. An attendee never needs an account, repository, or keyboard.

## What this demo shows

Omnigent is a **meta-harness**: it coordinates the coding agents teams already use. In this demo, Polly sends multiple agent harnesses to investigate a real bug and make dependent changes in isolated Git worktrees. The presenter can enter any child session, inspect its files and diff, and show a policy approval from the same interface.

A booth conversation normally lasts **5–10 minutes**. Do not try to show every section. Ask what the attendee cares about and jump there.

## Before the event

### Workspace requirements

Use your own Databricks workspace. Confirm all of these before booth duty:

- Omnigent preview is enabled.
- Databricks Sandbox preview is enabled.
- The workspace region supports Sandbox and Unity AI Gateway.
- Serverless egress control is not enabled for this Sandbox path.
- **Polly** appears in the Omnigent agent picker.
- At least two Polly worker vendors are available.
- `https://github.com/databricks-solutions/devrel-examples` contains `demos/omnigent` on branch `omnigent-conference-demo`.
- You can start a Sandbox session against that public repository without GitHub credentials.

### Prepare a completed session

Before booth duty, run the complete demo once using the prompts below. Leave that session available as a backup for completed diffs and reviews.

### Two-minute preflight

Immediately before booth duty:

1. Open `<your-workspace>/omnigent`.
2. Open the completed rehearsal session and confirm its child sessions and files still load.
3. Open one implementation child and confirm **Changes → Show diff** works.
4. If the rehearsal produced a local review, confirm that report is visible.
5. Start a fresh Sandbox session through the setup steps below and reach **READY**.
6. If you plan to show AI Gateway, open the prepared usage dashboard or saved query now.
7. If you plan to show the phone view, open the target session on your exact phone and network now.

## Start a fresh live session

In workspace/omnigent:

![Prompt 0 ready to submit in a new Omnigent session configured with Polly, Databricks Sandbox, and the devrel-examples demo branch.](assets/start-fresh-live-session.png)

1. Select **New session**.
2. Select agent **Polly**.
3. Select host **Sandbox**.
4. Set repository to:

   ```text
   https://github.com/databricks-solutions/devrel-examples
   ```

5. Set branch to:

   ```text
   omnigent-conference-demo
   ```

6. Paste **Prompt 0**.

The public repository supplies the code. This demo does not require GitHub credentials and does not push or open pull requests.

## Prompt 0 — prepare and show the problem

```text
Prepare this workspace for the Omnigent issue-triage demo.

Verify that demos/omnigent exists, then run the documented setup for demos/omnigent/issue-triage. Do not modify git remotes.

Run the naive issue-triage client against the public omnigent-ai/omnigent repository. Report the item count and top labels exactly as observed. Do not change source code or tests. Stop after reporting READY or a specific blocker.
```

### What to point out

The demo repository contains a deliberately thin Python CLI that calls GitHub's public Issues API, counts a repository's open issues, and groups them by label. It worked against a small repository. Against the active Omnigent repository, its hidden assumptions become obvious—and Polly has a concrete problem to investigate and fix.

The CLI normally reports exactly **30** items because it reads one default API page. Labels associated with pull requests can appear in what it calls an issue summary. Exact labels and repository totals change over time; the stable signal is “one page and mixed object types,” not a memorized count beyond 30.

Suggested line:

> “This worked on a tiny repository. Point it at an active tracker and the assumptions become visible.”

## Ask what the attendee cares about

Use this menu privately; do not read it as a script.

- **Multiple agents / orchestration** → run Prompt 1 and show the task graph.
- **Actual coding work** → run Prompt 2 and open an implementation child.
- **Isolation** → show that each implementation has its own worktree and branch.
- **Review** → open a different-vendor review if Polly created one; otherwise show the local diff and tests.
- **Human control / governance** → add the approval policy.
- **Databricks integration** → show the prepared AI Gateway usage view.
- **Remote collaboration** → optionally open the same session on your phone.

## Prompt 1 — ask Polly to triage the problem

```text
/investigate This GitHub issue-triage client worked on a small repository, but its output for omnigent-ai/omnigent looks wrong. Use multiple read-only agents to find the problems, report evidence from the code and live GitHub API, and recommend the order in which they should be fixed. Do not edit code or tests yet.
```

### Key narrative

Open the task graph and one or both investigation children.

Suggested lines:

> “Claude Code, Codex, Pi, and other tools are individual harnesses. Omnigent sits above them and coordinates the work.”

> “I can enter any child session, see what it is doing, and redirect it. I am not copying findings between separate tools.”

> “The important result is not ‘use more agents.’ It is deciding what must happen first and what can safely separate.”

Expected findings:

- The client reads only the first page and ignores GitHub's `Link: rel="next"` response.
- GitHub's Issues endpoint also returns pull-request objects.
- Pagination changes the client interface used by issue listing, so pagination must be completed first.
- Pull-request filtering should be implemented from the reviewed pagination result, not in parallel from the original seed.

## Prompt 2 — fix what Polly found

```text
Implement the issues from your investigation, working only under demos/omnigent/issue-triage. At minimum, add Link-header pagination first on branch feat/ghlite-pagination, with focused regression tests; then base branch feat/ghlite-filter-prs on that completed result and filter objects containing the pull_request key from the issue list, again with focused regression tests. Report any other findings as follow-up work rather than expanding this demo. Use separate local worktrees where appropriate. Keep all work local: do not push, open a pull request, or merge into the starting branch.

If your standard review flow requires a pull request, stop after producing the local worktree changes and passing tests. Report that limitation clearly; do not try to configure GitHub credentials. Finish by reporting the final stacked branch and the exact fast-forward merge command for the presenter.
```

This can take longer than a booth conversation. Let it run while discussing the graph and children. If the attendee wants completed artifacts immediately, open your completed rehearsal session.

## Show the code and worktrees

From the task graph or Subagents panel:

1. Open the pagination implementation child.
2. Open **Changes**.
3. Select a changed file such as `ghlite/client.py` or `ghlite/issues.py`.
4. Select **Show diff**; use split or unified view according to screen size.
5. Return to Polly and, if it created a local review session, open the reviewer.
6. If review was unavailable without a pull request, show the local diff and test result instead.
7. Open the filtering child and show its smaller incremental diff.

Suggested lines:

> “Each implementation agent gets an isolated Git worktree. Their edits do not collide in one shared directory.”

> “Polly can route an implementation to another model for an independent view. In this rehearsal, the guaranteed artifacts are the local worktree, diff, and tests.”

## Merge the reviewed result into the starting branch

Polly deliberately leaves merging to the human. In the top-level session, open a terminal and run:

```bash
git merge --ff-only feat/ghlite-filter-prs
cd demos/omnigent/issue-triage
.venv/bin/python -m pytest -q
cd ../../..
```

The final filtering branch is stacked on the pagination branch, so this one fast-forward lands both changes in dependency order. Nothing is pushed.

Return to the top-level session, open **Changes**, and select **Show diff** on `ghlite/client.py` or `ghlite/issues.py`. The starting session now shows the combined change rather than leaving it visible only inside child worktrees.

Suggested line:

> “Polly delivers reviewed branches; the human decides what lands. Once I fast-forward the local starting branch, Omnigent shows the combined diff here.”

## Show a policy approval

After the coding flow—or in the completed rehearsal session:

1. Open the top-level session's information panel.
2. Under **Policies**, select **Add**.
3. Add the built-in **Require Approval for File & Shell Operations** policy (`ask_on_os_tools`).
4. Send:

   ```text
   Read demos/omnigent/README.md and summarize its first paragraph.
   ```

5. Show the approval card and select **Approve**.

Suggested line:

> “Policies run at the Omnigent layer. This session can pause a tool action for approval regardless of which model is driving the conversation.”

Do not claim that a policy attached to the top-level session automatically governed every child session. That inheritance is not part of this demonstration.

## Optional: show AI Gateway usage

Sandbox model calls route through the workspace's Foundation Model APIs over Unity AI Gateway automatically.

![Workspace AI Gateway Usage Analytics showing requests, token usage, latency, endpoints, models, and coding agents.](assets/ai-gateway-usage-analytics.png)

Open a **prepared** AI Gateway Usage dashboard or saved query over `system.ai_gateway.usage`. Point out whichever fields are already populated:

- request and model-service count;
- requested endpoint and actual destination model;
- requester;
- status and latency;
- input, output, and total tokens.

Suggested line:

> “The models are supplied through the presenter's Databricks workspace, so the same AI Gateway governance and usage records apply.”

Do not wait for the current request to appear. Usage-table ingestion has no published immediate-visibility guarantee, and the built-in dashboard may refresh slowly. Use prepared historical data or a saved prior run. Treat cost, inference tables, and unified traces as optional modules only when preconfigured and populated.

## Optional: phone view

Show this only if it passed preflight on the exact device and network.

Open the managed workspace in the Omnigent native mobile app using your own authenticated workspace identity, then open the same session. Use the laptop if approval or navigation is unreliable. Never improvise a public tunnel or expose a local Omnigent server at the booth.

## Reset for the next attendee

In the current top-level session, send:

```text
Reset this demo workspace for the next attendee.

Run demos/omnigent/scripts/reset_demo.py --yes using the issue-triage virtual
environment. Confirm that Polly worktrees and local task branches are gone,
runtime artifacts are removed, the starting branch is clean, and the seed tests
pass. Preserve the public origin remote. Report READY or the exact remaining
state.
```

Expected result:

```text
READY: starting branch restored; no local task branches/worktrees/artifacts; seed tests pass
```

Reset returns the starting branch to the commit recorded during setup, then removes the demo worktrees and branches. If reset does not report **READY**, stop using that session. Start a new Sandbox session from the public repository rather than debugging in front of an attendee.

## OSS fallback

Use this only when the presenter's workspace lacks Omnigent/Sandbox access.

Requirements:

- local Omnigent installation;
- Python 3.12+, Node.js 22 LTS, npm, and tmux;
- at least two authenticated worker vendors for the independent-review claim;
- the public `devrel-examples` repository.

From a terminal:

```bash
git clone --depth 1 --filter=blob:none --sparse \
  --branch omnigent-conference-demo \
  https://github.com/databricks-solutions/devrel-examples.git omnigent-demo
cd omnigent-demo
git sparse-checkout set demos/omnigent

cd demos/omnigent/issue-triage
./scripts/setup.sh
cd ../../..

omni polly
```

Then use Prompts 0–2 and the same reset command. The OSS path does not include Databricks Sandbox or AI Gateway observability.

## If something fails

| Problem | Response |
|---|---|
| Polly missing from picker | Managed setup is incomplete. Use OSS fallback or the completed session. |
| `demos/omnigent` missing | The public demo contents are not on the selected branch. Stop. |
| Public clone fails | Start one fresh Sandbox. If it fails again, use fallback. |
| Fewer than two worker vendors available | Do not claim independent cross-vendor review. Use completed session or fallback. |
| Live work is slow | Keep discussing the graph or open the completed rehearsal session. |
| Changes list is empty | Confirm you opened the implementation child, not only the top-level orchestrator. |
| Policy does not trigger | Use a fresh ordinary session for the policy module; do not disrupt the coding run. |
| Current AI Gateway row is absent | Show prepared historical usage; do not wait or claim immediate ingestion. |
| Reset is not READY | Abandon that Sandbox and start a fresh session. |

## Close

Suggested closer:

> “The point is not another coding agent. Omnigent is the layer that composes the agents, gives each one a safe place to work, routes their artifacts and reviews, and applies governance across the session.”
