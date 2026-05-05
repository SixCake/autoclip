#!/usr/bin/env bash
# v0.8.7.2 部分跑批 wrapper — 仅跑指定 material 列表 (复用 _realvideo_dispatcher.py)
#
# 与 run_v087_batch.sh 的区别:
#   - run_v087_batch.sh 跑全 5 部 (固定 MATERIALS 数组)
#   - run_v087_partial.sh 跑指定列表 (CLI 位置参数, 用于 K3 决策只补跑叙事性视频)
#   - 不清理 v087_batch/ 已有目录 (保留 01/02 历史 FAILED 记录, 仅覆盖列表中的)
#   - 追加而非覆盖 _results.tsv (保留之前的 FAILED 行, 用 ${MATERIAL} 去重)
#
# Usage:
#   ./scripts/run_v087_partial.sh <whisper_model> <target_duration_sec> <material1> [material2] ...
#
# Example (K3 补跑 03/04/05):
#   ./scripts/run_v087_partial.sh large-v3 60 03_movie_review 04_short_drama 05_vlog

set -uo pipefail

if [[ $# -lt 3 ]]; then
  echo "❌ Usage: $0 <whisper_model> <target_duration_sec> <material1> [material2] ..." >&2
  exit 1
fi

WHISPER_MODEL="$1"
TARGET_DURATION_SEC="$2"
shift 2
MATERIALS=("$@")

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

RAW_DIR="${REPO_ROOT}/data/realvideo_test/raw_v087"
BATCH_OUT_DIR="${REPO_ROOT}/data/realvideo_test/v087_batch"
mkdir -p "${BATCH_OUT_DIR}"

# Env 注入 (与 run_v087_batch.sh 完全一致)
if [[ -z "${HF_ENDPOINT:-}" ]]; then export HF_ENDPOINT=https://hf-mirror.com; fi
if [[ -z "${HF_HUB_DOWNLOAD_TIMEOUT:-}" ]]; then export HF_HUB_DOWNLOAD_TIMEOUT=60; fi
export AUTOCLIP_LLM_PROVIDER="${AUTOCLIP_LLM_PROVIDER:-deepseek}"
export WHISPER_MODEL_SIZE="${WHISPER_MODEL}"

RESULTS_FILE="${BATCH_OUT_DIR}/_results.tsv"
# 如果不存在则建表头, 否则追加
if [[ ! -f "${RESULTS_FILE}" ]]; then
  echo -e "material\tstatus\telapsed_sec\ttimeline_segments\thook_candidates\tpersona_id\terror" > "${RESULTS_FILE}"
fi

echo "════════════════════════════════════════════════════════════"
echo "🎬 v0.8.7.2 Partial Batch (K3: 仅补跑叙事性视频)"
echo "════════════════════════════════════════════════════════════"
echo "  Whisper           : ${WHISPER_MODEL}"
echo "  Target duration   : ${TARGET_DURATION_SEC}s"
echo "  Materials         : ${MATERIALS[*]}"
echo "════════════════════════════════════════════════════════════"

BATCH_T0=$(date +%s)

for IDX in "${!MATERIALS[@]}"; do
  MATERIAL="${MATERIALS[$IDX]}"
  N=$((IDX + 1))
  RAW_VIDEO="${RAW_DIR}/${MATERIAL}.mp4"
  JOB_DIR="${BATCH_OUT_DIR}/${MATERIAL}"

  echo ""
  echo "▶▶▶ [${N}/${#MATERIALS[@]}] ${MATERIAL} ◀◀◀"

  if [[ ! -f "${RAW_VIDEO}" ]]; then
    echo "  ❌ raw mp4 not found: ${RAW_VIDEO}"
    echo -e "${MATERIAL}\tFAILED\t0\t0\t0\t-\traw_not_found" >> "${RESULTS_FILE}"
    continue
  fi

  # 清理该 material 旧目录 (重跑保证干净)
  rm -rf "${JOB_DIR}"
  mkdir -p "${JOB_DIR}/raw"
  cp "${RAW_VIDEO}" "${JOB_DIR}/raw/${MATERIAL}.mp4"

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
    echo "  ❌ FAILED (exit=${EXIT_CODE}, ${ELAPSED}s)"
    LAST_ERR="$(tail -5 "${JOB_DIR}/dispatcher.log" | tr '\n' ' ' | head -c 200)"
    echo -e "${MATERIAL}\tFAILED\t${ELAPSED}\t0\t0\t-\t${LAST_ERR}" >> "${RESULTS_FILE}"
    continue
  fi

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

echo ""
echo "════════════════════════════════════════════════════════════"
echo "📊 Partial batch done in ${BATCH_ELAPSED}s"
echo "  see ${RESULTS_FILE}"
echo "════════════════════════════════════════════════════════════"
