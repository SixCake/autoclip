"""Friendly error message mapper (M4.5).

Maps exception types → user-readable Chinese messages + next-step guidance.
Used by pipeline runner when a stage fails.
"""

from __future__ import annotations

_ERROR_MAP: list[tuple[str, str, str]] = [
    # (exception_type_fragment, chinese_message, next_step)
    ("NarrativeIRTooLargeError", "视频太长，ASR文本超出LLM处理上限", "请尝试上传5分钟以内的短片"),
    ("PlotOutlineError", "剧情大纲生成失败，可能是视频内容LLM无法理解", "请重试，或更换内容更清晰的视频"),
    ("PersonaInferenceError", "UP主人格推断失败", "请重试，如持续失败请联系开发者"),
    ("JianyingExportError", "剪映草稿包导出失败", "请检查磁盘空间，或使用JSON时间线格式下载"),
    ("RenderValidationError", "草稿包验证失败（路径包含绝对路径）", "请联系开发者，这是系统内部错误"),
    ("FileNotFoundError", "必要文件缺失，上游阶段可能未完成", "请重试任务，如持续失败请联系开发者"),
    ("TimeoutError", "处理超时", "请尝试上传更短的视频，或稍后重试"),
    ("ConnectionError", "网络连接失败", "请检查网络连接，稍后重试"),
    ("HTTPError", "外部服务请求失败（LLM/TTS API）", "请稍后重试，或检查API密钥配置"),
    ("JSONDecodeError", "LLM返回内容解析失败", "请重试，LLM偶发性输出格式错误"),
    ("ValueError", "数据格式错误", "请重试，如持续失败请联系开发者"),
    ("MemoryError", "内存不足", "请关闭其他程序后重试，或使用更短的视频"),
    ("cancelled", "任务被用户取消", "如需重新处理请上传新任务"),
]

_DEFAULT_MESSAGE = "未知错误"
_DEFAULT_NEXT_STEP = "请重试，如持续失败请联系开发者"


def get_friendly_error(error_str: str) -> dict[str, str]:
    """Map an error string to a friendly Chinese message + next step.

    Args:
        error_str: Error string from state.json (format: "ExceptionType: message")

    Returns:
        Dict with 'message' and 'next_step' keys.
    """
    error_lower = error_str.lower()

    for exception_fragment, chinese_message, next_step in _ERROR_MAP:
        if exception_fragment.lower() in error_lower:
            return {
                "type": exception_fragment,
                "message": chinese_message,
                "next_step": next_step,
                "raw": error_str,
            }

    return {
        "type": "Unknown",
        "message": _DEFAULT_MESSAGE,
        "next_step": _DEFAULT_NEXT_STEP,
        "raw": error_str,
    }
