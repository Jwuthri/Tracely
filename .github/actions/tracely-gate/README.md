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

## Example workflow

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

      # 1) Replay YOUR agent on the promoted cases, emitting traces tagged tracely.env=ci.
      #    Instrument with the Tracely SDK and call tracely_sdk.init(env="ci"). This step is
      #    yours — Tracely can't run your agent for you.
      - name: Replay agent on regression suite
        env:
          TRACELY_API: ${{ secrets.TRACELY_API }}
          TRACELY_KEY: ${{ secrets.TRACELY_KEY }}
        run: |
          pip install tracely-sdk
          python ci/replay_agent.py

      # 2) Gate the PR on the result.
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

The same CLI runs outside CI — it just skips the GitHub posting (or use `--dry-run` to preview it):

```bash
pip install ./sdk                       # or: pip install tracely-sdk
TRACELY_API=http://localhost:8000 tracely gate planner --env ci
```
