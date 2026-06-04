# `tracely-gate` action

Gate a pull request on an agent's **production-derived regression suite**. Tracely promotes
real production failures into fail-to-pass regression cases; this action replays them against
the PR and turns the result into a blocking commit status (`tracely/regression-gate`) plus an
upserted PR comment.

## Inputs

| input | required | default | description |
|---|---|---|---|
| `agent` | ✅ | — | agent slug whose PROMOTED suite to run |
| `api` | ✅ | — | Tracely API base URL |
| `key` | ✅ | — | Tracely API / ingest key (use a secret) |
| `web-url` | | `""` | Tracely web base URL, for the "view gate run" link |
| `env` | | `ci` | the `tracely.env` tag your CI traces were emitted with |
| `github-token` | | `${{ github.token }}` | token used to post the status + comment |
| `sdk-spec` | | `tracely-sdk` | pip spec for the SDK/CLI (override with a git URL until published) |

There are two ways to use it. **Replay is the turnkey path:** one CLI step re-runs your agent
on every promoted case and gates the PR. The composite action is for when your CI already
emits ci-tagged traces and you just want the gate.

### Turnkey: `tracely replay` (recommended)

`tracely replay` fetches the promoted suite, re-runs your agent on each recorded input
(emitting ci traces), pairs each trace to its case, gates, and posts the check — in one step.

```yaml
name: Tracely regression gate
on: pull_request

permissions:
  contents: read
  statuses: write        # the blocking commit status
  pull-requests: write   # the results comment

jobs:
  gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - env:
          TRACELY_API: ${{ secrets.TRACELY_API }}
          TRACELY_KEY: ${{ secrets.TRACELY_KEY }}
          TRACELY_WEB_URL: ${{ secrets.TRACELY_WEB_URL }}
        run: |
          pip install tracely-sdk        # + your agent's deps
          # your agent as module:function, called with each case input:
          tracely replay planner --entrypoint my_agent:run
          # ...or a non-Python agent (gets the input in $TRACELY_INPUT):
          # tracely replay planner --cmd "node run-agent.js"
```

**Hermetic by default.** Replay is deterministic and offline: each promoted case ships the
tool/LLM calls recorded in production (in order, with their args and error status), and an agent
written with `tracely.call_tool(name, fn, args=...)` / `tracely.call_llm(model, fn)` serves those
instead of making the real call — so CI needs no model key, costs nothing, and never flakes.
Repeated calls get their own recorded outputs, and a call that errored in production replays as an
error (so the gate reproduces the failure). Pass `--live` to make real calls instead.

### DIY emit + gate action

If your CI already emits ci-tagged traces (your harness calls `tracely_sdk.init(env="ci")`),
use the composite action to gate them:

```yaml
      - name: Emit ci traces
        run: python ci/run_agent.py      # your harness
      - uses: your-org/tracely/.github/actions/tracely-gate@main
        with:
          agent: planner
          api: ${{ secrets.TRACELY_API }}
          key: ${{ secrets.TRACELY_KEY }}
          web-url: ${{ secrets.TRACELY_WEB_URL }}
```

Mark **`tracely/regression-gate`** a required status check (Settings → Branches) to actually
block merges on a red gate.

## Run it locally

Both commands run outside CI — they just skip the GitHub posting (or use `--dry-run` to preview it):

```bash
pip install ./sdk                                          # provides the `tracely` CLI
TRACELY_API=http://localhost:8000 tracely replay planner --entrypoint my_agent:run
TRACELY_API=http://localhost:8000 tracely gate planner --env ci
```
