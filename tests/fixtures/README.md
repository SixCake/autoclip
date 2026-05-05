# E2E Test Fixtures

This directory contains fixture video files for E2E testing.

## Required Fixtures

| File | Type | Duration | Notes |
|------|------|----------|-------|
| `drama_5min.mp4` | 剧情片（对白密集） | ~5min | 验证 K1/K2/K3/K6 |
| `action_5min.mp4` | 动作片（镜头切换频繁） | ~5min | 验证镜头切分鲁棒性 |
| `anime_5min.mp4` | 动漫（日漫/国漫） | ~5min | 验证 PySceneDetect 阈值 |

## How to Obtain

1. 从公版/CC授权影视素材库获取（推荐：Archive.org / CC Search）
2. 或使用自己拍摄/制作的短片
3. 确认素材版权允许个人学习研究使用

## Copyright Note

这些测试素材仅用于本地学习研究，不上传至代码仓库（已在 .gitignore 中排除 `tests/fixtures/*.mp4`）。

## Running E2E Tests

```bash
# 启动服务
poetry run uvicorn autoclip.main:app --host 0.0.0.0 --port 8000

# 在另一个终端运行 E2E
poetry run python scripts/e2e_run.py --video tests/fixtures/drama_5min.mp4 --duration 90 --style plot_summary
poetry run python scripts/e2e_run.py --video tests/fixtures/action_5min.mp4 --duration 90 --style humor_roast
poetry run python scripts/e2e_run.py --video tests/fixtures/anime_5min.mp4 --duration 90 --style serious_review
```
