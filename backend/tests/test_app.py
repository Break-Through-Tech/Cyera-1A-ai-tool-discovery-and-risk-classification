def test_health_reports_ok(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_unknown_route_returns_application_error_body(client):
    response = client.get("/no-such-route")

    assert response.status_code == 404
    assert response.json() == {"code": "not_found", "message": "Resource not found."}
