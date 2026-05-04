"""Unit tests for autoclip.utils.ffmpeg — command builders + probe parsing.

These tests must NOT invoke real ffmpeg / ffprobe; the real-binary path
is exercised in tests/integration/test_ingest.py (default skip).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from autoclip.utils.ffmpeg import (
    AUDIO_CHANNELS,
    AUDIO_CODEC,
    AUDIO_SAMPLE_RATE,
    HD_AUDIO_BITRATE,
    HD_MAX_HEIGHT,
    HD_VIDEO_CRF,
    LOW_AUDIO_BITRATE,
    LOW_TARGET_FPS,
    LOW_TARGET_HEIGHT,
    LOW_VIDEO_CRF,
    X264_PRESET,
    FFmpegNotFoundError,
    ProbeError,
    ProbeResult,
    _parse_fps,
    _parse_probe_json,
    build_extract_audio_cmd,
    build_normalize_hd_cmd,
    build_normalize_low_cmd,
    probe_video,
)

# ===== Constants sanity =====


def test_constants_match_adr_010():
    """If anyone changes a constant, this test forces re-reading ADR-010."""
    assert LOW_TARGET_HEIGHT == 720
    assert LOW_TARGET_FPS == 25
    assert LOW_VIDEO_CRF == 23
    assert LOW_AUDIO_BITRATE == "128k"
    assert HD_MAX_HEIGHT == 1080
    assert HD_VIDEO_CRF == 21
    assert HD_AUDIO_BITRATE == "192k"
    assert X264_PRESET == "medium"
    assert AUDIO_SAMPLE_RATE == 16000
    assert AUDIO_CHANNELS == 1
    assert AUDIO_CODEC == "pcm_s16le"


# ===== _parse_fps =====


def test_parse_fps_normal_ratio():
    assert _parse_fps("30000/1001") == pytest.approx(29.97, rel=1e-3)


def test_parse_fps_simple_integer_ratio():
    assert _parse_fps("25/1") == 25.0


def test_parse_fps_zero_denominator():
    """ffprobe returns '0/0' for streams without a stable framerate."""
    assert _parse_fps("0/0") == 0.0


def test_parse_fps_empty_or_invalid():
    assert _parse_fps("") == 0.0
    assert _parse_fps("garbage") == 0.0
    assert _parse_fps("abc/def") == 0.0


# ===== _parse_probe_json =====


def _video_stream(width=1920, height=1080, fps_str="25/1", codec="h264"):
    return {
        "codec_type": "video",
        "codec_name": codec,
        "width": width,
        "height": height,
        "avg_frame_rate": fps_str,
        "r_frame_rate": fps_str,
    }


def _audio_stream(codec="aac"):
    return {"codec_type": "audio", "codec_name": codec}


def test_probe_json_full_video_with_audio():
    data = {
        "streams": [_video_stream(), _audio_stream()],
        "format": {"duration": "120.5"},
    }
    result = _parse_probe_json(data, Path("/fake.mp4"))
    assert result.width == 1920
    assert result.height == 1080
    assert result.fps == 25.0
    assert result.duration_sec == 120.5
    assert result.video_codec == "h264"
    assert result.audio_codec == "aac"
    assert result.has_audio is True


def test_probe_json_video_only_no_audio():
    data = {"streams": [_video_stream()], "format": {"duration": "10.0"}}
    result = _parse_probe_json(data, Path("/fake.mp4"))
    assert result.has_audio is False
    assert result.audio_codec is None


def test_probe_json_user_actual_video_1376x768():
    """User test fixture: 英语启蒙误区与脑科学.mp4 — 1376x768 (sub-1080p)."""
    data = {
        "streams": [_video_stream(width=1376, height=768, fps_str="24/1"), _audio_stream()],
        "format": {"duration": "628.796"},
    }
    result = _parse_probe_json(data, Path("/fake.mp4"))
    assert result.width == 1376
    assert result.height == 768
    assert result.fps == 24.0
    assert result.duration_sec == pytest.approx(628.796)
    # Sub-1080p source: hd_target_height should equal source height (no upscale).
    assert result.hd_target_height() == 768


def test_probe_json_4k_source_caps_at_1080p():
    """4K source should be capped at 1080 for hd track (no need to render at 4K)."""
    data = {
        "streams": [_video_stream(width=3840, height=2160), _audio_stream()],
        "format": {"duration": "60.0"},
    }
    result = _parse_probe_json(data, Path("/fake.mp4"))
    assert result.height == 2160
    assert result.hd_target_height() == HD_MAX_HEIGHT  # 1080


def test_probe_json_no_video_stream_raises():
    data = {"streams": [_audio_stream()], "format": {"duration": "10.0"}}
    with pytest.raises(ProbeError, match="no video stream"):
        _parse_probe_json(data, Path("/fake.mp4"))


def test_probe_json_zero_dimensions_raises():
    bad_video = {**_video_stream(), "width": 0, "height": 0}
    data = {"streams": [bad_video], "format": {"duration": "10.0"}}
    with pytest.raises(ProbeError, match="invalid video dimensions"):
        _parse_probe_json(data, Path("/fake.mp4"))


def test_probe_json_falls_back_to_r_frame_rate():
    """avg_frame_rate=0/0 should fall through to r_frame_rate."""
    bad_avg_video = _video_stream()
    bad_avg_video["avg_frame_rate"] = "0/0"
    bad_avg_video["r_frame_rate"] = "30/1"
    data = {"streams": [bad_avg_video], "format": {"duration": "10.0"}}
    result = _parse_probe_json(data, Path("/fake.mp4"))
    assert result.fps == 30.0


# ===== probe_video (with mocked subprocess) =====


def test_probe_video_missing_file_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError, match="video file not found"):
        probe_video(tmp_path / "nope.mp4")


def test_probe_video_missing_ffprobe_binary_raises(tmp_path):
    src = tmp_path / "fake.mp4"
    src.write_bytes(b"fake")
    with (
        patch("autoclip.utils.ffmpeg.shutil.which", return_value=None),
        pytest.raises(FFmpegNotFoundError, match="ffprobe"),
    ):
        probe_video(src)


def test_probe_video_subprocess_failure_raises_probe_error(tmp_path):
    src = tmp_path / "fake.mp4"
    src.write_bytes(b"fake")
    err = subprocess.CalledProcessError(returncode=1, cmd=["ffprobe"], stderr="bad input")
    with (
        patch("autoclip.utils.ffmpeg.shutil.which", return_value="/usr/bin/ffprobe"),
        patch("autoclip.utils.ffmpeg.subprocess.run", side_effect=err),
        pytest.raises(ProbeError, match="ffprobe failed"),
    ):
        probe_video(src)


def test_probe_video_invalid_json_raises(tmp_path):
    src = tmp_path / "fake.mp4"
    src.write_bytes(b"fake")
    fake_run = MagicMock(return_value=MagicMock(stdout="not-json", stderr=""))
    with (
        patch("autoclip.utils.ffmpeg.shutil.which", return_value="/usr/bin/ffprobe"),
        patch("autoclip.utils.ffmpeg.subprocess.run", fake_run),
        pytest.raises(ProbeError, match="non-JSON"),
    ):
        probe_video(src)


def test_probe_video_happy_path(tmp_path):
    src = tmp_path / "fake.mp4"
    src.write_bytes(b"fake")
    fake_json = (
        '{"streams":[{"codec_type":"video","codec_name":"h264","width":1920,'
        '"height":1080,"avg_frame_rate":"25/1","r_frame_rate":"25/1"},'
        '{"codec_type":"audio","codec_name":"aac"}],'
        '"format":{"duration":"42.0"}}'
    )
    fake_run = MagicMock(return_value=MagicMock(stdout=fake_json, stderr=""))
    with (
        patch("autoclip.utils.ffmpeg.shutil.which", return_value="/usr/bin/ffprobe"),
        patch("autoclip.utils.ffmpeg.subprocess.run", fake_run),
    ):
        result = probe_video(src)
    assert isinstance(result, ProbeResult)
    assert result.width == 1920
    assert result.duration_sec == 42.0


# ===== build_normalize_low_cmd =====


def test_low_cmd_starts_with_ffmpeg_and_overwrite():
    cmd = build_normalize_low_cmd(Path("/in.mp4"), Path("/out.mp4"))
    assert cmd[0] == "ffmpeg"
    assert "-y" in cmd


def test_low_cmd_uses_correct_filter_chain():
    cmd = build_normalize_low_cmd(Path("/in.mp4"), Path("/out.mp4"))
    vf_idx = cmd.index("-vf")
    assert cmd[vf_idx + 1] == f"scale=-2:{LOW_TARGET_HEIGHT},fps={LOW_TARGET_FPS}"


def test_low_cmd_uses_libx264_with_correct_crf_and_preset():
    cmd = build_normalize_low_cmd(Path("/in.mp4"), Path("/out.mp4"))
    assert cmd[cmd.index("-c:v") + 1] == "libx264"
    assert cmd[cmd.index("-crf") + 1] == str(LOW_VIDEO_CRF)
    assert cmd[cmd.index("-preset") + 1] == X264_PRESET


def test_low_cmd_includes_aac_audio_with_128k_bitrate():
    cmd = build_normalize_low_cmd(Path("/in.mp4"), Path("/out.mp4"))
    assert cmd[cmd.index("-c:a") + 1] == "aac"
    assert cmd[cmd.index("-b:a") + 1] == LOW_AUDIO_BITRATE


def test_low_cmd_enables_faststart():
    cmd = build_normalize_low_cmd(Path("/in.mp4"), Path("/out.mp4"))
    assert cmd[cmd.index("-movflags") + 1] == "+faststart"


def test_low_cmd_passes_paths_as_strings():
    cmd = build_normalize_low_cmd(Path("/in.mp4"), Path("/out.mp4"))
    assert "/in.mp4" in cmd
    assert "/out.mp4" in cmd
    assert all(isinstance(arg, str) for arg in cmd)


# ===== build_normalize_hd_cmd =====


def test_hd_cmd_caps_at_1080_for_4k_source():
    cmd = build_normalize_hd_cmd(Path("/in.mp4"), Path("/out.mp4"), source_height=2160)
    vf = cmd[cmd.index("-vf") + 1]
    assert vf == f"scale=-2:{HD_MAX_HEIGHT}"


def test_hd_cmd_no_upscale_for_sub_hd_source():
    """User actual video: 1376x768 → hd target should stay at 768."""
    cmd = build_normalize_hd_cmd(Path("/in.mp4"), Path("/out.mp4"), source_height=768)
    vf = cmd[cmd.index("-vf") + 1]
    assert vf == "scale=-2:768"


def test_hd_cmd_keeps_source_fps_no_fps_filter():
    """Unlike low, hd must NOT force 25fps — keep source fps for render quality."""
    cmd = build_normalize_hd_cmd(Path("/in.mp4"), Path("/out.mp4"), source_height=1080)
    vf = cmd[cmd.index("-vf") + 1]
    assert "fps=" not in vf


def test_hd_cmd_uses_higher_quality_crf_and_audio():
    cmd = build_normalize_hd_cmd(Path("/in.mp4"), Path("/out.mp4"), source_height=1080)
    assert cmd[cmd.index("-crf") + 1] == str(HD_VIDEO_CRF)
    assert cmd[cmd.index("-b:a") + 1] == HD_AUDIO_BITRATE


def test_hd_cmd_zero_or_negative_height_raises():
    with pytest.raises(ValueError, match="source_height must be positive"):
        build_normalize_hd_cmd(Path("/in.mp4"), Path("/out.mp4"), source_height=0)
    with pytest.raises(ValueError, match="source_height must be positive"):
        build_normalize_hd_cmd(Path("/in.mp4"), Path("/out.mp4"), source_height=-1)


# ===== build_extract_audio_cmd =====


def test_audio_cmd_drops_video_stream():
    cmd = build_extract_audio_cmd(Path("/in.mp4"), Path("/out.wav"))
    assert "-vn" in cmd


def test_audio_cmd_uses_16khz_mono_pcm_s16le():
    cmd = build_extract_audio_cmd(Path("/in.mp4"), Path("/out.wav"))
    assert cmd[cmd.index("-ar") + 1] == str(AUDIO_SAMPLE_RATE)
    assert cmd[cmd.index("-ac") + 1] == str(AUDIO_CHANNELS)
    assert cmd[cmd.index("-c:a") + 1] == AUDIO_CODEC


def test_audio_cmd_starts_with_ffmpeg_and_overwrite():
    cmd = build_extract_audio_cmd(Path("/in.mp4"), Path("/out.wav"))
    assert cmd[0] == "ffmpeg"
    assert "-y" in cmd


def test_audio_cmd_passes_paths_correctly():
    cmd = build_extract_audio_cmd(Path("/audio_in.mp4"), Path("/extracted.wav"))
    assert "/audio_in.mp4" in cmd
    assert "/extracted.wav" in cmd
    # output is the LAST positional arg (ffmpeg convention)
    assert cmd[-1] == "/extracted.wav"
