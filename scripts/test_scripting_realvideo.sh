#!/usr/bin/env bash
# 一键端到端验收 M2a Scripting 阶段 — 跑 INGEST → INDEX → SCRIPT 三阶段, 输出 timeline.json
#
# 不跑 ASSEMBLY/RENDER (M3 才实现, 否则 PipelineRunner 会 FAILED), 因此不复用 PipelineRunner.run(),
# 改为手动循环 dispatch 前 3 个 Stage 的 _stage_entrypoint (mp.Process spawn).
#
# Usage:
#   ./scripts/test_scripting_realvideo.sh <video_path> [target_duration_sec=60] [provider=deepseek] [whisper_model=tiny]
#
# Examples:
#   # 默认: target=60s, deepseek, whisper tiny
#   ./scripts/test_scripting_realvideo.sh ~/Downloads/test.mp4
#
#   # dashscope 兜底路径 + 90s target + medium 模型
#   ./scripts/test_scripting_realvideo.sh ~/Downloads/test.mp4 90 dashscope medium
#
# 前置依赖 (.env 中):
#   - DEEPSEEK_API_KEY (provider=deepseek 时必须)
#   - DASHSCOPE_API_KEY (provider=dashscope 时必须)
#
# 产物保留在: data/realvideo_test/job_<timestamp>/
#   - raw/<filename>           原视频拷贝 (M1.6 ingest 入口约定)
#   - normalized/, audio.wav   M1.6 ingest 产物 (audio.wav 由 M1.8 cleanup, 这里 RENDER 没跑所以保留)
#   - shots.json               M1.7 shot detector 产物
#   - asr.json                 M1.8 LocalWhisperProvider 产物
#   - llm_calls/scripting_*.json  M2a.6 K3 callback 落盘 (≥2 个: plot_outline + narrative_ir)
#   - timeline.json            M2a.6 final 产物
#   - state.json               5 stage 状态 (前 3 个 DONE, 后 2 个 PENDING)

set -euo pipefail

# ===== 参数 =====
VIDEO="${1:-}"
TARGET_DURATION_SEC="${2:-60}"
PROVIDER="${3:-deepseek}"
WHISPER_MODEL="${4:-tiny}"

if [[ -z "${VIDEO}" ]]; then
  echo "❌ Usage: $0 <video_path> [target_duration_sec=60] [provider=deepseek] [whisper_model=tiny]" >&2
  echo "" >&2
  echo "   provider     : deepseek (default) | dashscope" >&2
  echo "   whisper_model: tiny (default, 75MB) | base | small | medium (1.5GB) | large-v3 (3GB)" >&2
  exit 1
fi

# 展开 ~
VIDEO="${VIDEO/#\~/$HOME}"

if [[ ! -f "${VIDEO}" ]]; then
  echo "❌ Video file not found: ${VIDEO}" >&2
  exit 2
fi

if [[ "${PROVIDER}" != "deepseek" && "${PROVIDER}" != "dashscope" ]]; then
  echo "❌ provider must be 'deepseek' or 'dashscope', got: ${PROVIDER}" >&2
  exit 3
fi

# ===== 路径准备 =====
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

if [[ ! -x ".venv/bin/python" ]]; then
  echo "❌ .venv/bin/python not found — run 'poetry install' first" >&2
  exit 4
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "❌ ffmpeg not installed — run 'brew install ffmpeg'" >&2
  exit 5
fi

# HF mirror (R15: faster-whisper 模型走镜像源)
if [[ -z "${HF_ENDPOINT:-}" ]]; then
  export HF_ENDPOINT=https://hf-mirror.com
fi
if [[ -z "${HF_HUB_DOWNLOAD_TIMEOUT:-}" ]]; then
  export HF_HUB_DOWNLOAD_TIMEOUT=60
fi

# Provider 选择 (env 注入, factory.py 会读)
export AUTOCLIP_LLM_PROVIDER="${PROVIDER}"

# Whisper model size (config.py Settings.whisper_model_size 会读)
export WHISPER_MODEL_SIZE="${WHISPER_MODEL}"

# job_dir
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
JOB_DIR="${REPO_ROOT}/data/realvideo_test/job_${TIMESTAMP}"
mkdir -p "${JOB_DIR}/raw"

# 拷贝视频到 raw/ (ingest 入口约定: job_dir/raw/<filename>)
VIDEO_BASENAME="$(basename "${VIDEO}")"
RAW_VIDEO="${JOB_DIR}/raw/${VIDEO_BASENAME}"
cp "${VIDEO}" "${RAW_VIDEO}"

echo "════════════════════════════════════════════════════════════"
echo "🎬 M2a Scripting End-to-End Real-Video Acceptance"
echo "════════════════════════════════════════════════════════════"
echo "  Source video      : ${VIDEO}"
echo "  Job dir           : ${JOB_DIR}"
echo "  Target duration   : ${TARGET_DURATION_SEC}s"
echo "  LLM provider      : ${PROVIDER}"
echo "  Whisper model     : ${WHISPER_MODEL}"
echo "  HF_ENDPOINT       : ${HF_ENDPOINT}"
echo "════════════════════════════════════════════════════════════"
echo ""

# ===== 调用独立 dispatcher (避免 mp.spawn + heredoc/stdin 在 macOS 上崩) =====
T0=$(date +%s)

.venv/bin/python "${REPO_ROOT}/scripts/_realvideo_dispatcher.py" \
  "${JOB_DIR}" "${RAW_VIDEO}" "${TARGET_DURATION_SEC}"

T1=$(date +%s)
echo ""
echo "⏱  Total wall time: $((T1 - T0))s"
echo ""
echo "🧹 Cleanup (when done inspecting):"
echo "   rm -rf ${JOB_DIR}"
