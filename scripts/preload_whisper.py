#!/usr/bin/env python
"""Preload faster-whisper model weights to ~/.cache/huggingface/hub/.

Run this once before first M1.5 use to avoid blocking the pipeline on a 3GB
download (mitigates risk R15 in design.md Part IV §23).

Usage:
    python scripts/preload_whisper.py                  # default: large-v3
    python scripts/preload_whisper.py medium           # smaller model
    WHISPER_MODEL_SIZE=medium python scripts/preload_whisper.py
"""

from __future__ import annotations

import sys
import time

from autoclip.config import get_settings


def main() -> int:
    # CLI arg > env var > Settings default
    model_size = sys.argv[1] if len(sys.argv) > 1 else get_settings().whisper_model_size

    print(f"[preload] Loading faster-whisper model_size={model_size!r} ...")
    t0 = time.time()

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print(
            "[preload] ERROR: faster-whisper not installed. Run `poetry install`.", file=sys.stderr
        )
        return 1

    try:
        WhisperModel(model_size_or_path=model_size, device="auto", compute_type="default")
    except Exception as e:  # noqa: BLE001 — we want to print any error verbatim
        print(f"[preload] ERROR: failed to load {model_size!r}: {e!r}", file=sys.stderr)
        return 2

    elapsed = time.time() - t0
    print(f"[preload] OK — model {model_size!r} ready in {elapsed:.1f}s.")
    print("[preload] Cache location: ~/.cache/huggingface/hub/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
