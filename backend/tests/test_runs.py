import re
import threading
from concurrent.futures import ThreadPoolExecutor

from app.pipeline import Phase
from tests.conftest import TEST_VERSIONS
from tests.test_batches import ACTIVITY_CSV, upload


def failing(name: str) -> Phase:
    def fail(_context):
        raise ValueError("emp_1 uploaded secret.docx")

    return Phase(name, fail)


def test_new_upload_executes_one_successful_analysis_run(client):
    batch = upload(client).json()

    run = batch["latest_run"]
    assert run["status"] == "succeeded"
    assert run["batch_id"] == batch["batch_id"]
    assert run["attempt_number"] == 1
    assert run["versions"] == TEST_VERSIONS
    assert re.fullmatch(r"[0-9a-f]{40}(-dirty)?", run["code_commit"])
    assert run["completed_at"] is not None
    assert run["failure"] is None
    assert batch["latest_successful_run_id"] == run["run_id"]
    assert client.get(f"/runs/{run['run_id']}").json() == run


def test_failed_analysis_keeps_batch_and_records_safe_failure(make_client):
    client = make_client(failing("classify"))

    response = upload(client)

    assert response.status_code == 201
    batch = response.json()
    run = batch["latest_run"]
    assert run["status"] == "failed"
    assert run["completed_at"] is not None
    assert run["failure"] == {
        "summary": "Analysis failed during the classify phase.",
        "phase": "classify",
    }
    assert batch["latest_successful_run_id"] is None
    assert client.get(f"/batches/{batch['batch_id']}").json() == batch


def test_reanalysis_creates_a_distinct_run(client):
    batch = upload(client).json()
    first_run = batch["latest_run"]

    response = client.post(f"/batches/{batch['batch_id']}/runs")

    assert response.status_code == 201
    run = response.json()
    assert run["run_id"] != first_run["run_id"]
    assert run["attempt_number"] == 2
    assert run["status"] == "succeeded"
    assert client.get(f"/runs/{first_run['run_id']}").json() == first_run
    reopened = client.get(f"/batches/{batch['batch_id']}").json()
    assert reopened["latest_run"] == run
    assert reopened["latest_successful_run_id"] == run["run_id"]


def test_failed_reanalysis_keeps_prior_successful_run(make_client):
    calls = []

    def fail_after_first_run(_context):
        calls.append(None)
        if len(calls) > 1:
            raise RuntimeError("model unavailable")

    client = make_client(Phase("detect", fail_after_first_run))
    batch = upload(client).json()

    failed = client.post(f"/batches/{batch['batch_id']}/runs").json()

    assert failed["status"] == "failed"
    reopened = client.get(f"/batches/{batch['batch_id']}").json()
    assert reopened["latest_run"] == failed
    assert reopened["latest_successful_run_id"] == batch["latest_run"]["run_id"]


def test_execution_requests_conflict_while_batch_has_running_run(make_client):
    reanalysis_started = threading.Event()
    release = threading.Event()
    calls = []

    def pause_during_reanalysis(_context):
        calls.append(None)
        if len(calls) > 1:
            reanalysis_started.set()
            release.wait(timeout=10)

    client = make_client(Phase("detect", pause_during_reanalysis))
    batch_id = upload(client).json()["batch_id"]

    with ThreadPoolExecutor(max_workers=1) as pool:
        in_progress = pool.submit(client.post, f"/batches/{batch_id}/runs")
        assert reanalysis_started.wait(timeout=10)
        try:
            conflict = client.post(f"/batches/{batch_id}/runs")
            reopened = upload(client)
        finally:
            release.set()
        finished = in_progress.result(timeout=10).json()

    assert conflict.status_code == 409
    assert conflict.json()["code"] == "run_in_progress"
    assert reopened.status_code == 200
    assert reopened.json()["latest_run"]["status"] == "running"
    assert finished["status"] == "succeeded"
    assert finished["attempt_number"] == 2


def test_different_batches_analyze_concurrently(make_client):
    both_running = threading.Barrier(2, timeout=10)
    client = make_client(Phase("detect", lambda _context: both_running.wait()))
    uploads = [ACTIVITY_CSV, ACTIVITY_CSV.replace(b"evt_", b"other_evt_")]

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda content: upload(client, content), uploads))

    assert [r.status_code for r in responses] == [201, 201]
    assert [r.json()["latest_run"]["status"] for r in responses] == [
        "succeeded",
        "succeeded",
    ]


def test_restart_marks_interrupted_running_run_as_failed(make_client):
    seen_after_restart = {}

    def restart_mid_run(context):
        restarted = make_client()
        seen_after_restart.update(restarted.get(f"/runs/{context.run_id}").json())

    upload_response = upload(make_client(Phase("enrich", restart_mid_run))).json()

    assert seen_after_restart["status"] == "failed"
    assert seen_after_restart["completed_at"] is not None
    assert seen_after_restart["failure"] == {
        "summary": "Analysis was interrupted before completion.",
        "phase": None,
    }
    assert upload_response["latest_run"] == seen_after_restart


def test_unknown_run_returns_not_found(client):
    response = client.get("/runs/run_missing")

    assert response.status_code == 404
    assert response.json()["code"] == "run_not_found"


def test_reanalysis_of_unknown_batch_returns_not_found(client):
    response = client.post("/batches/bat_missing/runs")

    assert response.status_code == 404
    assert response.json()["code"] == "batch_not_found"
