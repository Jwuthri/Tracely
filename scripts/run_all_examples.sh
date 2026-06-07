#!/usr/bin/env bash
# Run every example in sdk/examples/ in sequence and push their traces to the local Tracely API.
#
# Usage:
#   scripts/run_all_examples.sh                  # run everything that has its key/dep available
#   scripts/run_all_examples.sh --wipe           # wipe ClickHouse traces + PG derived tables first
#   scripts/run_all_examples.sh --only openai    # filter by substring (e.g. "openai", "anthropic")
#
# Each example is expected to be self-guarding (prints a setup hint and exits 0 when its API key or
# instrumentor isn't available), so a missing key SKIPs rather than fails. Honors:
#   TRACELY_API (default http://localhost:8000)
#   TRACELY_KEY (default tracely_dev_key)

set -euo pipefail

cd "$(dirname "$0")/.."

WIPE=0
ONLY=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --wipe)  WIPE=1; shift ;;
    --only)  ONLY="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,12p' "$0"; exit 0 ;;
    *)
      echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

API="${TRACELY_API:-http://localhost:8000}"
KEY="${TRACELY_KEY:-tracely_dev_key}"

# colors (no-op if non-tty)
if [[ -t 1 ]]; then
  C_BOLD=$'\033[1m'; C_DIM=$'\033[2m'; C_OK=$'\033[32m'; C_WARN=$'\033[33m'; C_ERR=$'\033[31m'; C_OFF=$'\033[0m'
else
  C_BOLD=""; C_DIM=""; C_OK=""; C_WARN=""; C_ERR=""; C_OFF=""
fi

if [[ $WIPE -eq 1 ]]; then
  echo "${C_BOLD}wiping traces…${C_OFF}"
  curl -sf -H "Authorization: Bearer $KEY" "${API%/}/api/sessions?limit=1" >/dev/null \
    || { echo "${C_ERR}backend not reachable at $API${C_OFF}"; exit 1; }
  curl -s 'http://localhost:8123/' --data-binary 'TRUNCATE TABLE tracely.events' >/dev/null || true
  curl -s 'http://localhost:8123/' --data-binary 'TRUNCATE TABLE tracely.scores' >/dev/null || true
  docker exec tracely-postgres-1 psql -U tracely -d tracely -q -c \
    "TRUNCATE TABLE agents, agent_versions, case_replays, cluster_members, evaluation_cases, evaluation_suite_cases, evaluation_suites, failure_clusters, failure_embeddings, gate_cases, gate_runs RESTART IDENTITY CASCADE;" \
    >/dev/null 2>&1 || true
  echo "  done"
fi

# Order: a couple of provider SDKs first (the most common path), then harnesses, then the
# manual + drop-in. Examples requiring keys other than OPENAI silently skip when the key isn't set.
EXAMPLES=(
  auto_openai.py
  auto_agent.py
  auto_anthropic.py
  auto_gemini.py
  auto_mistral.py
  auto_bedrock.py
  auto_langchain.py
  auto_langgraph.py
  auto_litellm.py
  auto_llama_index.py
  auto_crewai.py
  auto_openai_agents.py
  auto_claude_agent.py
  auto_google_adk.py
  auto_openrouter.py
  dropin_openai.py
  dropin_anthropic.py
  manual_spans.py
)

ran=0; skipped=0; failed=0
for f in "${EXAMPLES[@]}"; do
  if [[ -n "$ONLY" && "$f" != *"$ONLY"* ]]; then continue; fi
  printf "${C_BOLD}▸ %s${C_OFF}\n" "$f"
  start=$(date +%s)
  # Capture last line for SKIP detection. We `set +e` for the run so a single example doesn't
  # halt the suite — the example layers already guard on key/dep absence.
  set +e
  out=$(TRACELY_API="$API" TRACELY_KEY="$KEY" uv run --no-sync python "sdk/examples/$f" 2>&1)
  rc=$?
  set -e
  elapsed=$(( $(date +%s) - start ))
  if [[ $rc -ne 0 ]]; then
    echo "${C_ERR}  ✗ failed (exit $rc, ${elapsed}s)${C_OFF}"
    echo "$out" | tail -8 | sed 's/^/    /'
    failed=$(( failed + 1 ))
  elif echo "$out" | tail -3 | grep -qiE "Set .*_API_KEY|pip install|not active|needs"; then
    echo "${C_WARN}  ↷ skipped — ${elapsed}s${C_OFF}"
    echo "$out" | tail -2 | sed 's/^/    /'
    skipped=$(( skipped + 1 ))
  else
    echo "${C_OK}  ✓ ${elapsed}s${C_OFF}"
    echo "$out" | tail -1 | sed 's/^/    /'
    ran=$(( ran + 1 ))
  fi
done

echo
echo "${C_BOLD}summary:${C_OFF} ${C_OK}${ran} ran${C_OFF}  ${C_WARN}${skipped} skipped${C_OFF}  ${C_ERR}${failed} failed${C_OFF}"
echo "${C_DIM}open the UI: http://localhost:3001/traces${C_OFF}"
[[ $failed -eq 0 ]]
