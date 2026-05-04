#!/usr/bin/env bash
# 一键测试 LocalWhisperProvider —— 用真实视频验证 faster-whisper 在 M3 Pro 上的端到端表现。
#
# Usage:
#   ./scripts/test_whisper_realvideo.sh <video_path> [model_size_or_path] [start_sec] [duration_sec]
#
# 第二参数智能识别 (R15 缓解 - 三档兜底):
#   - 模型名 (tiny/base/small/medium/large-v3): 走 huggingface_hub 下载, HF_ENDPOINT 默认 hf-mirror.com
#   - 本地路径 (含 / 或 ~ 或绝对路径): 直接用本地 CTranslate2 模型目录, 完全离线
#
# Examples:
#   # 默认: tiny 模型, 自动走 hf-mirror.com 镜像 (~75MB)
#   ./scripts/test_whisper_realvideo.sh ~/Downloads/movie.mp4
#
#   # 用本地预下载好的模型 (推荐生产场景, 完全离线无网络依赖)
#   ./scripts/test_whisper_realvideo.sh ~/Downloads/movie.mp4 ~/whisper_models/faster-whisper-tiny
#
#   # large-v3 真模型, 抽 60s-90s 的 30 秒音频 (生产质量验证)
#   ./scripts/test_whisper_realvideo.sh ~/Downloads/movie.mp4 large-v3 60 30
#
#   # 抽 5 分钟做实时率测试 (期望 M3 Pro 4-5x 实时率, large-v3 5min 音频 ~60-75s 出结果)
#   ./scripts/test_whisper_realvideo.sh ~/Downloads/movie.mp4 large-v3 0 300
#
# 网络问题排查 (R15):
#   1. 默认本脚本会 export HF_ENDPOINT=https://hf-mirror.com (除非用户已自行设置)
#   2. 如果镜像也不通, 手动下载到本地后用第二参数传本地路径:
#        mkdir -p ~/whisper_models/faster-whisper-tiny && cd ~/whisper_models/faster-whisper-tiny
#        for f in config.json model.bin tokenizer.json vocabulary.txt preprocessor_config.json; do
#          curl -L -o "$f" "https://hf-mirror.com/Systran/faster-whisper-tiny/resolve/main/$f"
#        done

set -euo pipefail

# ===== 参数 =====
VIDEO="${1:-}"
MODEL_ARG="${2:-tiny}"
START_SEC="${3:-0}"
DURATION_SEC="${4:-30}"

if [[ -z "${VIDEO}" ]]; then
  echo "❌ Usage: $0 <video_path> [model_size_or_path=tiny] [start_sec=0] [duration_sec=30]" >&2
  echo ""
  echo "   第二参数可以是模型名 OR 本地路径:"
  echo "     模型名 : tiny (75MB) / base / small / medium (1.5GB) / large-v3 (3GB)"
  echo "     本地路径: ~/whisper_models/faster-whisper-tiny (完全离线, 推荐 R15 兜底)"
  exit 1
fi

if [[ ! -f "${VIDEO}" ]]; then
  echo "❌ Video file not found: ${VIDEO}" >&2
  exit 2
fi

# ===== R15 缓解: 智能识别第二参数 + 默认走镜像源 =====
# 包含 / 或 ~ 视为本地路径; 否则视为模型名走 hub 下载
if [[ "${MODEL_ARG}" == */* || "${MODEL_ARG}" == ~* ]]; then
  # 本地路径: 展开 ~ 并校验存在
  MODEL_PATH="${MODEL_ARG/#\~/$HOME}"
  if [[ ! -d "${MODEL_PATH}" ]]; then
    echo "❌ Local model directory not found: ${MODEL_PATH}" >&2
    echo "   预下载方法见脚本顶部 'R15 网络问题排查' 段落" >&2
    exit 5
  fi
  MODEL_SIZE="${MODEL_PATH}"
  MODEL_LABEL="local:${MODEL_PATH}"
else
  # 模型名: 走 huggingface_hub 下载, 默认配 hf-mirror.com (除非用户自行 export 过)
  MODEL_SIZE="${MODEL_ARG}"
  MODEL_LABEL="hub:${MODEL_ARG}"
  if [[ -z "${HF_ENDPOINT:-}" ]]; then
    export HF_ENDPOINT=https://hf-mirror.com
    echo "ℹ️  HF_ENDPOINT not set; defaulting to https://hf-mirror.com (R15 mitigation)" >&2
  fi
  if [[ -z "${HF_HUB_DOWNLOAD_TIMEOUT:-}" ]]; then
    export HF_HUB_DOWNLOAD_TIMEOUT=60
  fi
fi

# ===== 路径准备 =====
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

if [[ ! -x ".venv/bin/python" ]]; then
  echo "❌ .venv/bin/python not found — run 'poetry install' first" >&2
  exit 3
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "❌ ffmpeg not installed — run 'brew install ffmpeg'" >&2
  exit 4
fi

OUT_DIR="${REPO_ROOT}/data/whisper_test"
mkdir -p "${OUT_DIR}"
AUDIO_WAV="${OUT_DIR}/$(basename "${VIDEO%.*}")_${START_SEC}s_${DURATION_SEC}s.wav"

# ===== Step 1: ffmpeg 抽音频 (16kHz mono pcm_s16le, 与 M1.6 Ingest 计划一致) =====
echo "════════════════════════════════════════════════════════════"
echo "🎬 Source video : ${VIDEO}"
echo "🎯 Model        : ${MODEL_LABEL}"
echo "🌐 HF_ENDPOINT  : ${HF_ENDPOINT:-<unset, local mode>}"
echo "⏱  Audio segment : ${START_SEC}s ~ $((START_SEC + DURATION_SEC))s (${DURATION_SEC}s)"
echo "💾 Output WAV   : ${AUDIO_WAV}"
echo "════════════════════════════════════════════════════════════"
echo ""
echo "[1/2] 🎵 Extracting audio with ffmpeg ..."
T0=$(date +%s)

ffmpeg -y -loglevel error \
  -ss "${START_SEC}" -t "${DURATION_SEC}" -i "${VIDEO}" \
  -vn -ac 1 -ar 16000 -c:a pcm_s16le \
  "${AUDIO_WAV}"

AUDIO_SIZE=$(ls -lh "${AUDIO_WAV}" | awk '{print $5}')
T1=$(date +%s)
echo "   ✅ Audio extracted (${AUDIO_SIZE}, $((T1 - T0))s)"
echo ""

# ===== Step 2: 跑 LocalWhisperProvider =====
echo "[2/2] 🧠 Transcribing with LocalWhisperProvider (model=${MODEL_LABEL}) ..."
echo "   (首次走 hub 下载 large-v3 约 ~3GB, 请耐心等待; 本地路径模式则秒开)"
echo ""

.venv/bin/python - <<PYEOF
import time
from pathlib import Path
from autoclip.providers.asr.local_whisper import LocalWhisperProvider

audio_path = Path("${AUDIO_WAV}")
duration_input = ${DURATION_SEC}
model_arg = r"""${MODEL_SIZE}"""

print(f"  → Loading model {model_arg!r} (device=auto, compute_type=default) ...")
t0 = time.time()
provider = LocalWhisperProvider(model_size=model_arg)
result = provider.transcribe(audio_path, language="zh")
elapsed = time.time() - t0

print()
print("════════════════════════════════════════════════════════════")
print(f"✅ Transcription DONE in {elapsed:.1f}s")
print(f"   Audio duration  : {duration_input}s")
print(f"   Wall time       : {elapsed:.1f}s")
print(f"   Realtime ratio  : {duration_input / elapsed:.2f}x  (目标 M3 Pro large-v3 ≥ 4x)")
print(f"   Detected lang   : {result.language}")
print(f"   Provider tag    : {result.provider}")
print(f"   Sentence count  : {len(result.sentences)}")
print(f"   Total speech    : {result.total_duration_sec:.1f}s (静音被 VAD 跳过)")
print("════════════════════════════════════════════════════════════")
print()
print("📝 Recognized sentences:")
print()
for s in result.sentences:
    print(f"  [{s.idx:>3}] {s.start_sec:>6.2f}s → {s.end_sec:>6.2f}s  (conf={s.confidence:>+6.3f}, speaker={s.speaker})")
    print(f"        {s.text}")
PYEOF

echo ""
echo "════════════════════════════════════════════════════════════"
echo "✨ Test complete. Audio kept at: ${AUDIO_WAV}"
echo "   (清理: rm -rf ${OUT_DIR})"
echo "════════════════════════════════════════════════════════════"
