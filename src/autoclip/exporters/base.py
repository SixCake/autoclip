"""DraftExporter base class — 4-track contract for video draft export."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TrackSegment:
    """One segment on a single track."""

    seg_id: str
    target_start_sec: float
    target_end_sec: float


@dataclass
class VideoTrackSegment(TrackSegment):
    source_path: str = "./materials/source.mp4"  # K10: placeholder always
    source_start_sec: float = 0.0
    source_end_sec: float = 0.0


@dataclass
class AudioTrackSegment(TrackSegment):
    audio_path: str = ""
    volume: float = 1.0


@dataclass
class SubtitleTrackSegment(TrackSegment):
    text: str = ""


@dataclass
class ExportResult:
    """Result of a single export operation."""

    output_path: Path
    exporter_name: str
    track_counts: dict[str, int] = field(default_factory=dict)
    # validation_passed is set by Render handler after K10 checks
    validation_passed: bool = False


class DraftExporter(ABC):
    """Abstract draft exporter — 4-track contract.

    All exporters MUST:
    1. Use placeholder paths (K10): source video = './materials/source.mp4'
    2. Produce 4 tracks: main_video / narration / original_audio / subtitle
    3. Pack output as a .zip file
    """

    PLACEHOLDER_SOURCE_PATH = "./materials/source.mp4"

    @abstractmethod
    def export(
        self,
        timeline: dict,
        assembly: dict,
        job_dir: Path,
        output_dir: Path,
    ) -> ExportResult:
        """Export a draft package.

        Args:
            timeline: Parsed timeline.json dict (segments, narrative_ir, etc.)
            assembly: Parsed assembly.json dict (sentences + TTS paths)
            job_dir: Job working directory (for resolving relative paths)
            output_dir: Where to write the output zip

        Returns:
            ExportResult with output_path set to the written zip.
        """

    @property
    @abstractmethod
    def name(self) -> str:
        """Exporter identifier string."""

    def _make_readme(self) -> str:
        """Standard README.txt content for the draft zip."""
        return (
            "AutoClip 自动生成草稿包\n"
            "========================\n\n"
            "使用方法：\n"
            "1. 用剪映导入本草稿包（文件 → 导入草稿）\n"
            "2. 将您的原始视频文件重命名为 source.mp4，放入 materials/ 文件夹\n"
            "3. 在剪映中刷新素材链接\n\n"
            "轨道说明：\n"
            "- 轨道1: 主视频（4段精剪片段）\n"
            "- 轨道2: AI解说配音（TTS合成）\n"
            "- 轨道3: 原视频音轨（已降至30%音量）\n"
            "- 轨道4: 字幕（与配音同步）\n\n"
            "注意：素材路径为占位符，需手动链接原视频。\n"
        )
