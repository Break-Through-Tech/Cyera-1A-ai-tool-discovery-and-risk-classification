# Backend

FastAPI + SQLAlchemy Core + SQLite API that ingests an activity CSV, analyzes it, and
serves the saved results. Domain vocabulary: [`CONTEXT.md`](../CONTEXT.md).

Run every command from this `backend/` directory.

## Install

Dependencies are pinned in `uv.lock`; `uv sync` creates `.venv` with the runtime and dev
(test) dependencies. Python 3.12 or newer.

```sh
uv sync
```

## Run the server

```sh
.venv/bin/uvicorn app.main:create_app --factory
```

The database and downloaded embedding model live in `APP_DATA_DIR` (default `backend/var`);
migrations run at startup. Analysis needs `TYPESAFE_API_KEY` (the Jev AI judge), read from
the environment or the repository-root `.env`; without it a Run fails in `ai_determination`.
`GET /health` answers `{"status":"ok"}`; the API is listed at `/docs`.

## Unit tests

```sh
.venv/bin/python -m pytest -q
```

No network, key or model download is needed.

## End-to-end check

`tests/test_end_to_end.py` uploads `data/synthetic_enterprise_activity/v1/activity.csv`
through `POST /batches`, then checks the overview, applications, contexts, events and
evidence it reads back against `evaluation_only/expected_scenarios.csv` and against each
other. Its docstring lists exactly which stages are real and which are faked.

Offline (deterministic; part of the unit suite):

```sh
.venv/bin/python -m pytest -q -s tests/test_end_to_end.py
```

Live (real homepages, Jev and embedding model; skipped unless `E2E_LIVE=1`). It prints the
Run's wall-clock time and every disagreement with the answer key, and fails on any:

```sh
# In-process, with a fresh database (the model cache in APP_DATA_DIR/models is reused):
E2E_LIVE=1 TYPESAFE_API_KEY=... .venv/bin/python -m pytest -s tests/test_end_to_end.py -k live

# Against a running server; an already-uploaded dataset is re-analyzed, replaying stored Jev answers:
E2E_LIVE=1 E2E_BASE_URL=http://127.0.0.1:8000 .venv/bin/python -m pytest -s tests/test_end_to_end.py -k live
```
