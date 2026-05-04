"""FFmpeg / ffprobe helpers for the Ingest stage (M1.6).

Reference: design.md Part IV §24 (ADR-010 dual-track normalize).

Design contract:
- `probe_video()` is the only function that actually invokes a subprocess;
  it returns a typed `ProbeResult` rather than raw JSON for downstream type safety.
- `build_*_cmd()` functions are pure: they return `list[str]` for safe
  `subprocess.run()` consumption (no shell=True, no quoting bugs).
- The hd track honors "no upscale" semantics: if source height < 1080 the
  output keeps the source height (avoids wasting CPU on synthetic detail).
- The low track always outputs 720p / 25fps for stable detection input.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

# Constants centralized here so handler / tests / docs stay in sync.
LOW_TARGET_HEIGHT = 720
LOW_TARGET_FPS = 25
LOW_VIDEO_CRF = 23
LOW_AUDIO_BITRATE = "128k"

HD_MAX_HEIGHT = 1080  # cap — we never upscale beyond this
HD_VIDEO_CRF = 21
HD_AUDIO_BITRATE = "192k"

X264_PRESET = "medium"

AUDIO_SAMPLE_RATE = 16000  # Hz — required by faster-whisper
AUDIO_CHANNELS = 1
AUDIO_CODEC = "pcm_s16le"

# Subprocess wall-clock cap for ffprobe (probe should be near-instant).
PROBE_TIMEOUT_SEC = 30


# ---------------------------------------------------------------------------
# ProbeResult
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProbeResult:
    """Typed projection of `ffprobe -show_streams -show_format` output.

    Only the fields the Ingest stage actually consumes are surfaced; the
    raw JSON is dropped to keep this dataclass small and serializable.
    """

    width: int
    height: int
    fps: float  # frames per second (float because ffprobe returns "30000/1001" style)
    duration_sec: float
    video_codec: str
    audio_codec: str | None  # None if the file has no audio stream
    has_audio: bool

    def hd_target_height(self) -> int:
        """Effective height for the hd normalize track (no upscale)."""
        return min(self.height, HD_MAX_HEIGHT)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class FFmpegNotFoundError(RuntimeError):
    """Raised when ffmpeg / ffprobe binary cannot be located on $PATH."""


class ProbeError(RuntimeError):
    """Raised when ffprobe fails or returns malformed JSON."""


# ---------------------------------------------------------------------------
# Probe
# ---------------------------------------------------------------------------


def _ensure_binary(name: str) -> str:
    """Return absolute path of `name` on $PATH, or raise FFmpegNotFoundError."""
    found = shutil.which(name)
    if found is None:
        raise FFmpegNotFoundError(
            f"{name!r} not found on PATH. Install via 'brew install ffmpeg' (macOS) "
            f"or 'apt install ffmpeg' (Debian/Ubuntu)."
        )
    return found


def _parse_fps(rate_str: str) -> float:
    """Parse ffprobe rate strings like '30000/1001', '25/1', '0/0'."""
    if not rate_str or "/" not in rate_str:
        return 0.0
    num_str, den_str = rate_str.split("/", 1)
    try:
        num = float(num_str)
        den = float(den_str)
    except ValueError:
        return 0.0
    if den == 0:
        return 0.0
    return num / den


def probe_video(src: Path) -> ProbeResult:
    """Run `ffprobe` on `src` and return a typed projection.

    Raises:
        FileNotFoundError: if `src` does not exist.
        FFmpegNotFoundError: if ffprobe is missing.
        ProbeError: if ffprobe fails, output is not JSON, or no video stream.
    """
    if not src.exists():
        raise FileNotFoundError(f"video file not found: {src}")

    ffprobe_bin = _ensure_binary("ffprobe")

    cmd = [
        ffprobe_bin,
        "-v",
        "error",
        "-show_streams",
        "-show_format",
        "-print_format",
        "json",
        str(src),
    ]
    try:
        result = subprocess.run(  # noqa: S603 — args list, no shell
            cmd,
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT_SEC,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise ProbeError(
            f"ffprobe failed (exit={exc.returncode}): {exc.stderr.strip()}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise ProbeError(f"ffprobe timed out after {PROBE_TIMEOUT_SEC}s") from exc

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ProbeError(f"ffprobe returned non-JSON output: {exc}") from exc

    return _parse_probe_json(data, src)


def _parse_probe_json(data: dict, src: Path) -> ProbeResult:
    """Pure helper: extract ProbeResult from a parsed ffprobe JSON dict.

    Split out so unit tests can feed canned JSON without invoking ffprobe.
    """
    streams = data.get("streams", [])
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

    if video_stream is None:
        raise ProbeError(f"no video stream found in {src}")

    width = int(video_stream.get("width", 0))
    height = int(video_stream.get("height", 0))
    if width <= 0 or height <= 0:
        raise ProbeError(f"invalid video dimensions in {src}: {width}x{height}")

    # Prefer avg_frame_rate; fall back to r_frame_rate.
    fps = _parse_fps(video_stream.get("avg_frame_rate", ""))
    if fps == 0.0:
        fps = _parse_fps(video_stream.get("r_frame_rate", ""))

    # Duration: format-level duration is more reliable than stream-level for many containers.
    fmt = data.get("format", {})
    duration_sec = float(fmt.get("duration", video_stream.get("duration", 0.0)) or 0.0)

    return ProbeResult(
        width=width,
        height=height,
        fps=fps,
        duration_sec=duration_sec,
        video_codec=str(video_stream.get("codec_name", "unknown")),
        audio_codec=str(audio_stream["codec_name"]) if audio_stream else None,
        has_audio=audio_stream is not None,
    )


# ---------------------------------------------------------------------------
# Command builders (pure)
# ---------------------------------------------------------------------------


def _common_normalize_tail(crf: int, audio_bitrate: str) -> list[str]:
    """Encoder + container settings shared by both low / hd builds."""
    return [
        "-c:v",
        "libx264",
        "-preset",
        X264_PRESET,
        "-crf",
        str(crf),
        "-pix_fmt",
        "yuv420p",  # widest compatibility (some 10-bit sources break QuickTime)
        "-c:a",
        "aac",
        "-b:a",
        audio_bitrate,
        "-movflags",
        "+faststart",
    ]


def build_normalize_low_cmd(src: Path, dst: Path) -> list[str]:
    """Build ffmpeg cmd for the low track: 720p @ 25fps for detection / ASR.

    Always re-encodes (no codec copy) — guarantees consistent input for
    PySceneDetect regardless of source codec.
    """
    return [
        "ffmpeg",
        "-y",  # overwrite if exists (resume scenarios)
        "-i",
        str(src),
        "-vf",
        f"scale=-2:{LOW_TARGET_HEIGHT},fps={LOW_TARGET_FPS}",
        *_common_normalize_tail(LOW_VIDEO_CRF, LOW_AUDIO_BITRATE),
        str(dst),
    ]


def build_normalize_hd_cmd(src: Path, dst: Path, source_height: int) -> list[str]:
    """Build ffmpeg cmd for the hd track: <=1080p, original fps, render-quality.

    Args:
        src: source video path.
        dst: target output path.
        source_height: pixel height of the source (from ProbeResult.height).
            Used to enforce no-upscale: target = min(source_height, 1080).
    """
    if source_height <= 0:
        raise ValueError(f"source_height must be positive, got {source_height}")

    target_height = min(source_height, HD_MAX_HEIGHT)
    return [
        "ffmpeg",
        "-y",
        "-i",
        str(src),
        "-vf",
        f"scale=-2:{target_height}",
        # Note: no `fps=` filter — we keep the source fps for hd render quality.
        *_common_normalize_tail(HD_VIDEO_CRF, HD_AUDIO_BITRATE),
        str(dst),
    ]


def build_extract_audio_cmd(src: Path, dst: Path) -> list[str]:
    """Build ffmpeg cmd to extract 16kHz mono pcm_s16le WAV for ASR input."""
    return [
        "ffmpeg",
        "-y",
        "-i",
        str(src),
        "-vn",  # drop video stream
        "-ac",
        str(AUDIO_CHANNELS),
        "-ar",
        str(AUDIO_SAMPLE_RATE),
        "-c:a",
        AUDIO_CODEC,
        str(dst),
    ]
