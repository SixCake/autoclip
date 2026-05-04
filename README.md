# AutoClip

AI-powered automatic video clip & narration generator (MVP).

## Quick Start

```bash
make install        # Install dependencies via Poetry
cp .env.example .env  # Fill in API keys
make run            # Start FastAPI dev server on :8000
```

## Documentation

- Design: [`docs/plans/2026-05-04-autoclip-design.md`](docs/plans/2026-05-04-autoclip-design.md)
- Plan: [`docs/plans/2026-05-04-autoclip-plan.md`](docs/plans/2026-05-04-autoclip-plan.md)

## Development

```bash
make test-unit      # Fast unit tests
make test           # All tests with coverage
make lint           # Ruff linter
make type-check     # Mypy type checker
```
