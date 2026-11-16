#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
unset LD_LIBRARY_PATH OPENAI_API_KEY OPENAI_BASE_URL

python=(.venv/bin/python -u)
data=data/ATBench/test.json
split=splits/atbench-v1.json
ipiguard_root=${IPIGUARD_ROOT:-/data1/yaoziao/IPIGuard}
run_id=${RUN_ID:-$(TZ=Asia/Shanghai date +%Y%m%d_%H%M%S_%N)}
mkdir -p results

agentdog=(--guard-model models/agentdog-4b --revision 3193b58d0c8924f5b5a79eb99cd31918e327024c)
atbench=(--data "$data" --split-manifest "$split")

run() {
    local name=$1
    shift
    local output="results/$name-$run_id"
    printf 'Writing %s.jsonl and %s.log\n' "$output" "$output"
    "${python[@]}" -m agentguard "$@" --output "$output.jsonl" 2>&1 | tee "$output.log"
}

case "${1:-}" in
    atbench-agentdog)
        run atbench-agentdog-replay atbench "${atbench[@]}" --method agentdog --replay "${agentdog[@]}"
        ;;
    atbench-deepseek)
        run atbench-deepseek atbench "${atbench[@]}" --method deepseek --env-file "$ipiguard_root/.env"
        ;;
    atbench-deepseek-author)
        run atbench-deepseek-author atbench "${atbench[@]}" --method deepseek --env-file "$ipiguard_root/.env" \
            --agentdog-author-prompt vendor/AgentDoG/prompts/v1.5/coarse_grained_moderation.txt --max-new-tokens 1024
        ;;
    atbench-safepred)
        run atbench-safepred atbench "${atbench[@]}" --method safepred --env-file "$ipiguard_root/.env"
        ;;
    atbench-safepred-tools)
        run atbench-safepred-tools atbench "${atbench[@]}" --method safepred --env-file "$ipiguard_root/.env" --include-tools
        ;;
    traces-train)
        : "${TRACES_RUN:?Set TRACES_RUN to a new directory under results/}"
        shift
        "${python[@]}" -m agentguard.traces_train --data "$data" --split-manifest "${TRACES_SPLIT:-$split}" \
            --observer models/qwen3-4b-observer --out-dir "$TRACES_RUN" "$@" 2>&1 | tee "results/traces-train-$run_id.log"
        ;;
    atbench-traces)
        : "${TRACES_RUN:?Set TRACES_RUN to the completed training directory}"
        run atbench-traces atbench --data "$data" --split-manifest "${TRACES_SPLIT:-$split}" \
            --method traces --traces-run "$TRACES_RUN"
        ;;
    dojo)
        method=${2:?Provide a guard method}
        mode=${3:?Provide benign or under_attack}
        shift 3
        suites=("$@")
        if (( ${#suites[@]} == 0 )); then
            suites=(workspace slack travel banking)
        fi
        options=()
        if [[ $method == agentdog ]]; then
            options+=("${agentdog[@]}")
        elif [[ $method == traces ]]; then
            : "${TRACES_RUN:?Set TRACES_RUN to the completed training directory}"
            options+=(--traces-run "$TRACES_RUN")
        fi
        for suite in "${suites[@]}"; do
            run "agentdojo-$method-$mode-$suite" agentdojo --ipiguard-root "$ipiguard_root" \
                --method "$method" --mode "$mode" --attack important_instructions --suite "$suite" --all-cases "${options[@]}"
        done
        ;;
    *)
        echo "Usage: $0 {atbench-agentdog|atbench-deepseek|atbench-deepseek-author|atbench-safepred|atbench-safepred-tools|traces-train|atbench-traces|dojo METHOD MODE [SUITE ...]}" >&2
        exit 2
        ;;
esac
