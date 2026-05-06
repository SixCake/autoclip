"""Unit tests for AUTOCLIP_CLEANUP_ENABLED switch (Session 34).

Verifiable goals:
- Default (env unset) → cleanup is OFF → all files preserved
- Truthy values ("1", "true", "yes", "on", case-insensitive) → cleanup ON
- Falsy / unknown values → cleanup OFF
- ON branch deletes source.mp4 + normalized.mp4 + temp/
- OFF branch writes one CLEANUP_DISABLED audit line
"""

from __future__ import annotations

from pathlib import Path

import pytest

from autoclip.compliance.cleanup import (
    _CLEANUP_ENABLED_ENV,
    _cleanup_enabled,
    cleanup_after_render,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def populated_job_dir(tmp_path: Path) -> Path:
    """Create a job dir with source.mp4 + normalized.mp4 + temp/ + tts/."""
    job_dir = tmp_path / "job_42"
    job_dir.mkdir()
    (job_dir / "source.mp4").write_bytes(b"\x00" * 2048)
    (job_dir / "normalized.mp4").write_bytes(b"\x00" * 1024)
    temp_dir = job_dir / "temp"
    temp_dir.mkdir()
    (temp_dir / "scratch.bin").write_bytes(b"x" * 64)
    tts_dir = job_dir / "tts"
    tts_dir.mkdir()
    (tts_dir / "tts_0000.wav").write_bytes(b"y" * 128)
    return job_dir


# ---------------------------------------------------------------------------
# _cleanup_enabled — env var parsing
# ---------------------------------------------------------------------------

class TestCleanupEnabledFlag:
    def test_unset_returns_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(_CLEANUP_ENABLED_ENV, raising=False)
        assert _cleanup_enabled() is False

    def test_empty_string_returns_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(_CLEANUP_ENABLED_ENV, "")
        assert _cleanup_enabled() is False

    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "True", "yes", "YES", "on", "ON"])
    def test_truthy_values_return_true(
        self, value: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(_CLEANUP_ENABLED_ENV, value)
        assert _cleanup_enabled() is True

    @pytest.mark.parametrize("value", ["0", "false", "no", "off", "FALSE", "disabled", "garbage"])
    def test_falsy_or_unknown_returns_false(
        self, value: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(_CLEANUP_ENABLED_ENV, value)
        assert _cleanup_enabled() is False


# ---------------------------------------------------------------------------
# cleanup_after_render — OFF branch (default)
# ---------------------------------------------------------------------------

class TestCleanupDisabledByDefault:
    def test_default_keeps_all_files(
        self, populated_job_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(_CLEANUP_ENABLED_ENV, raising=False)

        cleanup_after_render(populated_job_dir)

        # All artifacts preserved
        assert (populated_job_dir / "source.mp4").exists()
        assert (populated_job_dir / "normalized.mp4").exists()
        assert (populated_job_dir / "temp").exists()
        assert (populated_job_dir / "temp" / "scratch.bin").exists()
        assert (populated_job_dir / "tts" / "tts_0000.wav").exists()

    def test_default_writes_disabled_audit_line(
        self, populated_job_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(_CLEANUP_ENABLED_ENV, raising=False)

        cleanup_after_render(populated_job_dir)

        audit_log = populated_job_dir / "audit.log"
        assert audit_log.exists()
        log_text = audit_log.read_text(encoding="utf-8")
        assert "CLEANUP_DISABLED" in log_text
        assert _CLEANUP_ENABLED_ENV in log_text


# ---------------------------------------------------------------------------
# cleanup_after_render — ON branch
# ---------------------------------------------------------------------------

class TestCleanupEnabledExplicitly:
    def test_enabled_deletes_source_normalized_temp(
        self, populated_job_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(_CLEANUP_ENABLED_ENV, "true")

        cleanup_after_render(populated_job_dir)

        # source + normalized + temp/ deleted
        assert not (populated_job_dir / "source.mp4").exists()
        assert not (populated_job_dir / "normalized.mp4").exists()
        assert not (populated_job_dir / "temp").exists()

    def test_enabled_preserves_unrelated_artifacts(
        self, populated_job_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Even when enabled, cleanup only targets the documented file set;
        tts/ + other unlisted files stay (until explicit cron / future rule)."""
        monkeypatch.setenv(_CLEANUP_ENABLED_ENV, "1")

        cleanup_after_render(populated_job_dir)

        assert (populated_job_dir / "tts" / "tts_0000.wav").exists()

    def test_enabled_writes_per_file_audit_lines(
        self, populated_job_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(_CLEANUP_ENABLED_ENV, "yes")

        cleanup_after_render(populated_job_dir)

        log_text = (populated_job_dir / "audit.log").read_text(encoding="utf-8")
        assert "DELETE_FILE path=source.mp4" in log_text
        assert "DELETE_FILE path=normalized.mp4" in log_text
        assert "DELETE_DIR path=temp" in log_text
        # No DISABLED line when actually running
        assert "CLEANUP_DISABLED" not in log_text

    def test_enabled_with_missing_files_is_noop_safe(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Calling cleanup on a job dir that has none of the target files
        must not raise — the safe-delete helpers already handle absence."""
        monkeypatch.setenv(_CLEANUP_ENABLED_ENV, "true")
        empty_job = tmp_path / "empty_job"
        empty_job.mkdir()

        cleanup_after_render(empty_job)  # must not raise
