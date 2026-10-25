from fastapi.testclient import TestClient

from app.main import create_app


def client() -> TestClient:
    return TestClient(create_app())


def test_health_reports_ok():
    response = client().get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_unknown_route_returns_application_error_body():
    response = client().get("/no-such-route")

    assert response.status_code == 404
    assert response.json() == {"code": "not_found", "message": "Resource not found."}
