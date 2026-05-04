#!/usr/bin/env python
"""Preload faster-whisper model weights (mitigates risk R15 in design.md Part IV §23).

Behavior (R15 三档缓解):
1. 默认走 huggingface_hub 下载到 ~/.cache/huggingface/hub/
2. 自动 export HF_ENDPOINT=https://hf-mirror.com (除非用户已设置过, 国内网络友好)
3. 支持 --output-dir 把模型下载到指定目录, 之后可直接用本地路径吃模型 (production / 离线场景)

Usage:
    python scripts/preload_whisper.py                                  # default size, cache dir
    python scripts/preload_whisper.py medium                           # custom size
    python scripts/preload_whisper.py tiny --output-dir ~/whisper_models/faster-whisper-tiny
    HF_ENDPOINT=https://my-mirror.example.com python scripts/preload_whisper.py
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from autoclip.config import get_settings


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Preload faster-whisper model weights (R15 mitigation)."
    )
    parser.add_argument(
        "model_size",
        nargs="?",
        default=None,
        help="Model size (tiny/base/small/medium/large-v3). Default: Settings.whisper_model_size",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Download to this dir (instead of HF cache). Use with WHISPER_MODEL_SIZE=<dir>.",
    )
    args = parser.parse_args()

    model_size = args.model_size or get_settings().whisper_model_size

    # R15 缓解: 国内网络默认走 hf-mirror.com (除非用户已显式设置)
    if not os.environ.get("HF_ENDPOINT"):
        os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
        print("[preload] HF_ENDPOINT not set; defaulting to https://hf-mirror.com")
    if not os.environ.get("HF_HUB_DOWNLOAD_TIMEOUT"):
        os.environ["HF_HUB_DOWNLOAD_TIMEOUT"] = "60"

    print(f"[preload] Loading faster-whisper model_size={model_size!r} ...")
    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        print(f"[preload] Target output_dir: {args.output_dir}")

    t0 = time.time()
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print(
            "[preload] ERROR: faster-whisper not installed. Run `poetry install`.", file=sys.stderr
        )
        return 1

    try:
        if args.output_dir:
            # 下载到指定目录, 模型权重落到 args.output_dir/ 下
            from faster_whisper.utils import download_model

            local_path = download_model(model_size, output_dir=str(args.output_dir))
            print(f"[preload] Downloaded to: {local_path}")
            # 加载验证一次
            WhisperModel(model_size_or_path=str(args.output_dir), device="auto")
        else:
            # 默认行为: 走 HF cache
            WhisperModel(model_size_or_path=model_size, device="auto", compute_type="default")
    except Exception as e:  # noqa: BLE001 — we want to print any error verbatim
        print(f"[preload] ERROR: failed to load {model_size!r}: {e!r}", file=sys.stderr)
        print(
            "[preload] HINT: 若网络不通, 试试手动 wget:\n"
            f"  mkdir -p ~/whisper_models/faster-whisper-{model_size}\n"
            f"  cd ~/whisper_models/faster-whisper-{model_size}\n"
            f"  for f in config.json model.bin tokenizer.json vocabulary.txt preprocessor_config.json; do\n"
            f'    curl -L -o "$f" "https://hf-mirror.com/Systran/faster-whisper-{model_size}/resolve/main/$f"\n'
            f"  done\n"
            f"  # 然后用 LocalWhisperProvider(model_size='~/whisper_models/faster-whisper-{model_size}')",
            file=sys.stderr,
        )
        return 2

    elapsed = time.time() - t0
    print(f"[preload] OK — model {model_size!r} ready in {elapsed:.1f}s.")
    if args.output_dir:
        print(f"[preload] Use it via: WHISPER_MODEL_SIZE={args.output_dir.resolve()}")
    else:
        print("[preload] Cache location: ~/.cache/huggingface/hub/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
