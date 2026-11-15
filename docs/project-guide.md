# Local setup, API walkthrough, and evaluation

## Choose a workflow

| Goal | Start with | External calls |
| --- | --- | --- |
| Inspect sample data and recorded results | `notebooks/project_walkthrough.ipynb` | None; no model training or inference. |
| Run the API on a synthetic Batch | Backend instructions below | Homepage fetching, embedding download, and TypeSafe inference may occur. |
| Reproduce the original Category baseline | Baseline commands below | Dependency downloads; baseline runs locally. |

## Backend setup

Prerequisites: Git, Python 3.12 or later, and `uv`.

```sh
git clone https://github.com/Break-Through-Tech/Cyera-1A-ai-tool-discovery-and-risk-classification.git
cd Cyera-1A-ai-tool-discovery-and-risk-classification/backend
uv sync --frozen
```

`backend/pyproject.toml` and `backend/uv.lock` define the environment. The root `requirements.txt` is empty and is not the backend installer. Package availability must match the lockfile.

For live AI Determination, supply `TYPESAFE_API_KEY` through the environment or an untracked repository-root `.env`. Never commit credentials. The selected judge uses `jev-1.14.0`; provider availability and usage are separate from local tests.

```sh
uv run uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```

Application creation applies migrations and loads the checked-in catalog, exclusions, synthetic scenario metadata, and neighbor index. Local state defaults to `backend/var`; `APP_DATA_DIR` can select another directory. The embedding model may download when needed. Keep this prototype bound to localhost.

Visit `http://127.0.0.1:8000/docs` for generated API documentation or `http://127.0.0.1:8000/openapi.json` for the schema. Check `http://127.0.0.1:8000/health` first.

The optional assistant model is disabled unless `GEMINI_MODEL` is selected. A selected model requires `GEMINI_API_KEY`. This does not expose an assistant HTTP endpoint; see [integration status](assistant-integration.md).

## Analyst walkthrough

1. Use `data/synthetic_enterprise_activity/v1/activity.csv` and read its [data contract](../data/synthetic_enterprise_activity/v1/README.md).
2. In Swagger UI, call `POST /batches` with the CSV as multipart `file`. A new upload triggers analysis synchronously; identical bytes return the existing Batch.
3. Record `batch_id` and `latest_run`. Inspect status and failure details: upload acceptance alone does not establish analysis success.
4. Use `GET /batches/{batch_id}/runs` for history and `GET /runs/{run_id}` for a specific run.
5. For a succeeded run, use `GET /runs/{run_id}/assessments?tier=High` or `?flagged=true`. Review reasons, unknown facts, department, usage purpose, and rule version together.
6. Use `POST /batches/{batch_id}/runs` to reanalyze the immutable Batch. Preserve run IDs when comparing results.

From the repository root:

```sh
curl -F 'file=@data/synthetic_enterprise_activity/v1/activity.csv' http://127.0.0.1:8000/batches
```

This live path can contact vendor sites and a paid inference provider. No real employee telemetry is needed. Do not upload `evaluation_only/expected_scenarios.csv` or use it as retrieval evidence.

## API reference

| Method and path | Purpose |
| --- | --- |
| `GET /health` | Service health. |
| `POST /batches` | Validate/upload CSV and analyze a new Batch. |
| `GET /batches` | Paginated Batch directory. |
| `GET /batches/{batch_id}` | Metadata and latest-run references. |
| `POST /batches/{batch_id}/runs` | Start a new Analysis Run. |
| `GET /batches/{batch_id}/runs` | Paginated run history. |
| `GET /runs/{run_id}` | Status, versions, and failure details. |
| `GET /runs/{run_id}/assessments` | Paginated assessments; optional `tier` and `flagged`. |

Use OpenAPI for exact request/response fields. Invalid uploads return 422, missing resources 404, and an active run or results request for a non-succeeded run can return 409. Failed evidence retrieval does not prove that a Tool is non-AI.

## Training and evaluation

Runtime AI Determination is a gate plus a versioned external judge, not a fitted local classifier. Category Classification uses a frozen embedding model and training-description neighbor index. Historical fitted baselines remain useful comparisons.

To reproduce the original Category baseline in a separate environment, from the repository root:

```sh
python -m venv .venv-category
. .venv-category/bin/activate
python -m pip install -r notebooks/category_classification/requirements.txt
python -B notebooks/category_classification/prepare_dataset.py
python -B -m unittest discover -s notebooks/category_classification -p 'test_*.py'
python -B notebooks/category_classification/train_baseline.py
```

On Windows activate with `.venv-category\Scripts\Activate.ps1`. The script fits TF-IDF and logistic regression and writes `baseline_evaluation.json` in the Category dataset directory. This is not the deployed neighbor-vote model and can update tracked outputs; review the working tree afterward.

Inspect selected configurations through committed `FREEZE.json` and result files using the walkthrough notebook. `notebooks/category_classification/evaluate_test.py` refuses to overwrite its existing report. Do not delete it to claim a fresh test. New thresholds or prompts require newly frozen independent data. AI reruns can require credentials, caches, and provider usage; see [experiment history](../notebooks/ai_cascade/README.md).

## Verification

From `backend/`, after installation:

```sh
uv run pytest -q
```

From the repository root, validate the activity fixture without rewriting it:

```sh
python -B data/synthetic_enterprise_activity/v1/generate_activity.py --check
```

Backend tests use fixtures and mocked providers for relevant paths. They do not establish live model quality, production readiness, or complete analyst workflows. The offline walkthrough reports historical results and does not retrain models or contact external services.

## Verification notes for this documentation update

The locked backend dependencies installed successfully on Python 3.12. The local test environment required the optional `socksio` package because it uses a SOCKS proxy; this was an environment-only installation, not a lockfile change.

The activity generator's `--check` reported differences from the checked-in `activity.csv` and `evaluation_only/expected_scenarios.csv`. The existing fixture has been preserved. Reconcile generator determinism and the fixture before claiming byte-for-byte sample regeneration.

The four walkthrough code cells were executed sequentially in a shared Python namespace and the notebook schema was validated. A separate Jupyter kernel could not start in the verification sandbox because socket binding was restricted. No live provider calls or new model-training runs were performed.

Backend verification result: **288 tests and 7 subtests passed** after the environment-only proxy dependency installation.
