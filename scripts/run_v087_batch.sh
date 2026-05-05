#!/usr/bin/env bash
# v0.8.7 5-material batch dispatcher — 串行跑 5 部题材, 复用 _realvideo_dispatcher.py (SCRIPTING stop)
#
# 设计契约 (与 test_scripting_realvideo.sh 区别):
#   - 输入: data/realvideo_test/raw_v087/{01..05}_*.mp4 (5 部, 题材命名)
#   - 输出: data/realvideo_test/v087_batch/<material_name>/ (按题材命名而非时间戳, 便于评分追溯)
#   - 失败处理: 单部失败 continue 不退出, 最后 SUMMARY.md 汇总成功/失败
#
# Usage:
#   ./scripts/run_v087_batch.sh [target_duration_sec=60] [provider=deepseek] [whisper_model=tiny]
#
# 前置依赖 (.env 中):
#   - DEEPSEEK_API_KEY (provider=deepseek 时必须)

set -uo pipefail  # 注意: 不用 -e, 因为单部失败要 continue

# ===== 参数 =====
TARGET_DURATION_SEC="${1:-60}"
PROVIDER="${2:-deepseek}"
WHISPER_MODEL="${3:-tiny}"

# ===== 路径准备 =====
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

RAW_DIR="${REPO_ROOT}/data/realvideo_test/raw_v087"
BATCH_OUT_DIR="${REPO_ROOT}/data/realvideo_test/v087_batch"

if [[ ! -d "${RAW_DIR}" ]]; then
  echo "❌ Raw dir not found: ${RAW_DIR}" >&2
  exit 2
fi

if [[ ! -x ".venv/bin/python" ]]; then
  echo "❌ .venv/bin/python not found — run 'poetry install' first" >&2
  exit 4
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "❌ ffmpeg not installed — run 'brew install ffmpeg'" >&2
  exit 5
fi

mkdir -p "${BATCH_OUT_DIR}"

# Env 注入 (与 test_scripting_realvideo.sh 一致)
if [[ -z "${HF_ENDPOINT:-}" ]]; then
  export HF_ENDPOINT=https://hf-mirror.com
fi
if [[ -z "${HF_HUB_DOWNLOAD_TIMEOUT:-}" ]]; then
  export HF_HUB_DOWNLOAD_TIMEOUT=60
fi
export AUTOCLIP_LLM_PROVIDER="${PROVIDER}"
export WHISPER_MODEL_SIZE="${WHISPER_MODEL}"

# ===== 5 部素材列表 (固定, 按 v087-download 阶段确认) =====
MATERIALS=(
  "01_kids_song"
  "02_anime"
  "03_movie_review"
  "04_short_drama"
  "05_vlog"
)

# ===== 跑批 =====
echo "════════════════════════════════════════════════════════════"
echo "🎬 v0.8.7 5-Material Batch Run"
echo "════════════════════════════════════════════════════════════"
echo "  Raw dir           : ${RAW_DIR}"
echo "  Batch out dir     : ${BATCH_OUT_DIR}"
echo "  Target duration   : ${TARGET_DURATION_SEC}s"
echo "  LLM provider      : ${PROVIDER}"
echo "  Whisper model     : ${WHISPER_MODEL}"
echo "  Materials         : ${#MATERIALS[@]} (serial run)"
echo "════════════════════════════════════════════════════════════"
echo ""

BATCH_T0=$(date +%s)

# 临时记录每部的 success/fail/elapsed/timeline_path, 最后写 SUMMARY.md
RESULTS_FILE="${BATCH_OUT_DIR}/_results.tsv"
echo -e "material\tstatus\telapsed_sec\ttimeline_segments\thook_candidates\tpersona_id\terror" > "${RESULTS_FILE}"

for IDX in "${!MATERIALS[@]}"; do
  MATERIAL="${MATERIALS[$IDX]}"
  N=$((IDX + 1))
  RAW_VIDEO="${RAW_DIR}/${MATERIAL}.mp4"
  JOB_DIR="${BATCH_OUT_DIR}/${MATERIAL}"

  echo ""
  echo "▶▶▶ [${N}/${#MATERIALS[@]}] ${MATERIAL} ◀◀◀"
  echo "  raw      : ${RAW_VIDEO}"
  echo "  job_dir  : ${JOB_DIR}"

  if [[ ! -f "${RAW_VIDEO}" ]]; then
    echo "  ❌ raw mp4 not found, skipping"
    echo -e "${MATERIAL}\tFAILED\t0\t0\t0\t-\traw_not_found" >> "${RESULTS_FILE}"
    continue
  fi

  # job_dir 与 raw 准备 (复用 test_scripting_realvideo.sh 的约定)
  rm -rf "${JOB_DIR}"  # 重跑保证干净 (不 resume)
  mkdir -p "${JOB_DIR}/raw"
  cp "${RAW_VIDEO}" "${JOB_DIR}/raw/${MATERIAL}.mp4"

  # 调 dispatcher
  T0=$(date +%s)
  set +e
  .venv/bin/python "${REPO_ROOT}/scripts/_realvideo_dispatcher.py" \
    "${JOB_DIR}" "${JOB_DIR}/raw/${MATERIAL}.mp4" "${TARGET_DURATION_SEC}" \
    > "${JOB_DIR}/dispatcher.log" 2>&1
  EXIT_CODE=$?
  set -e
  T1=$(date +%s)
  ELAPSED=$((T1 - T0))

  if [[ ${EXIT_CODE} -ne 0 ]]; then
    echo "  ❌ dispatcher FAILED (exit=${EXIT_CODE}, ${ELAPSED}s) — see ${JOB_DIR}/dispatcher.log"
    LAST_ERR="$(tail -5 "${JOB_DIR}/dispatcher.log" | tr '\n' ' ' | head -c 200)"
    echo -e "${MATERIAL}\tFAILED\t${ELAPSED}\t0\t0\t-\t${LAST_ERR}" >> "${RESULTS_FILE}"
    continue
  fi

  # 提取 timeline.json 关键统计
  TL="${JOB_DIR}/timeline.json"
  if [[ ! -f "${TL}" ]]; then
    echo "  ⚠️  exit=0 but timeline.json missing"
    echo -e "${MATERIAL}\tFAILED\t${ELAPSED}\t0\t0\t-\ttimeline_missing" >> "${RESULTS_FILE}"
    continue
  fi

  N_SEG=$(.venv/bin/python -c "import json; t=json.load(open('${TL}')); print(len(t.get('segments',[])))")
  N_HOOK=$(.venv/bin/python -c "import json; t=json.load(open('${TL}')); hc=t.get('hook_candidates') or {}; print(len(hc.get('candidates',[])))")
  PERSONA=$(.venv/bin/python -c "import json; t=json.load(open('${TL}')); rp=t.get('recommended_persona') or {}; print(rp.get('persona_id','-'))")

  echo "  ✅ DONE in ${ELAPSED}s (segments=${N_SEG} hooks=${N_HOOK} persona=${PERSONA})"
  echo -e "${MATERIAL}\tOK\t${ELAPSED}\t${N_SEG}\t${N_HOOK}\t${PERSONA}\t-" >> "${RESULTS_FILE}"
done

BATCH_T1=$(date +%s)
BATCH_ELAPSED=$((BATCH_T1 - BATCH_T0))

# ===== SUMMARY =====
echo ""
echo "════════════════════════════════════════════════════════════"
echo "📊 Batch Summary"
echo "════════════════════════════════════════════════════════════"
column -t -s $'\t' "${RESULTS_FILE}"
echo ""
echo "⏱  Total wall time: ${BATCH_ELAPSED}s"
echo ""

# 写 markdown 报告供 v087-score 阶段使用
SUMMARY_MD="${BATCH_OUT_DIR}/SUMMARY.md"
{
  echo "# v0.8.7 Batch Run Summary"
  echo ""
  echo "- Run at: $(date '+%Y-%m-%d %H:%M:%S')"
  echo "- Provider: ${PROVIDER} / Whisper: ${WHISPER_MODEL} / target_duration: ${TARGET_DURATION_SEC}s"
  echo "- Total wall time: ${BATCH_ELAPSED}s"
  echo ""
  echo "## Results"
  echo ""
  echo "| material | status | elapsed_sec | segments | hooks | persona_id | error |"
  echo "|---|---|---|---|---|---|---|"
  tail -n +2 "${RESULTS_FILE}" | awk -F'\t' '{printf "| %s | %s | %s | %s | %s | %s | %s |\n", $1,$2,$3,$4,$5,$6,$7}'
  echo ""
  echo "## Per-job artifacts"
  echo ""
  for M in "${MATERIALS[@]}"; do
    echo "- \`${BATCH_OUT_DIR##*/}/${M}/\` — timeline.json + llm_calls/ + dispatcher.log"
  done
} > "${SUMMARY_MD}"

echo "📝 Markdown summary: ${SUMMARY_MD}"
echo "════════════════════════════════════════════════════════════"
