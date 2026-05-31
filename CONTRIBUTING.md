# Contributing to nodus-observability-framework

## Setup

```bash
git clone https://github.com/Masterplanner25/nodus-observability-framework.git
cd nodus-observability-framework
pip install -e ".[dev]"
pip install "nodus-observability>=0.1.0"
```

## Running tests

```bash
pytest tests/ -q
```

## Code style

- Python 3.11+
- All optional integrations (FastAPI, OTel, Prometheus) must degrade
  gracefully when their extra is absent — use `try/except ImportError`
- `create_registry()` must never use the global Prometheus registry
- `get_stream_registry()` singleton must be reset-safe between tests
- Do not commit `.bak` files

## Submitting changes

1. Fork the repo and create a branch from `main`
2. Add tests for any new behaviour
3. Ensure `pytest tests/ -q` passes
4. Open a pull request with a description of what changes and why
