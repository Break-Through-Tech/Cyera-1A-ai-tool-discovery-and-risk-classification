import json

import pytest

from app.ai_determination.jev import CachedJudge, JevClient, JudgeUnavailable, request_hash
from app.db.engine import migrate, open_database

BODY = {"model": "jev-1.14.0", "state": {"title": "Tool"}, "questions": {}}
RESPONSE = {"model": "jev-1.14.0", "answers": {"q": {"noul": 0.5}}, "usage": {"input_tokens": 1}}


class FakePost:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def __call__(self, data, headers):
        self.calls.append((json.loads(data), headers))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def ok():
    return 200, json.dumps(RESPONSE).encode()


def client(post, api_key="secret-key"):
    return JevClient(api_key, post=post, sleep=lambda seconds: None)


def test_client_sends_the_body_with_the_key_as_a_bearer_token():
    post = FakePost(ok())

    assert client(post)(BODY) == RESPONSE

    sent, headers = post.calls[0]
    assert sent == BODY
    assert headers["Authorization"] == "Bearer secret-key"


def test_client_retries_rate_limits_server_errors_and_network_failures():
    post = FakePost((429, b""), (503, b""), ConnectionResetError(), ok())

    assert client(post)(BODY) == RESPONSE
    assert len(post.calls) == 4


def test_client_gives_up_after_five_attempts():
    post = FakePost(*[(503, b"")] * 5)

    with pytest.raises(JudgeUnavailable):
        client(post)(BODY)
    assert len(post.calls) == 5


def test_client_does_not_retry_a_rejected_request():
    post = FakePost((401, b"bad key"))

    with pytest.raises(JudgeUnavailable):
        client(post)(BODY)
    assert len(post.calls) == 1


def test_client_without_a_key_is_unavailable_without_sending_anything():
    post = FakePost()

    with pytest.raises(JudgeUnavailable):
        client(post, api_key=None)(BODY)
    assert post.calls == []


def test_request_hash_ignores_key_order():
    reordered = {"questions": {}, "state": {"title": "Tool"}, "model": "jev-1.14.0"}

    assert request_hash(BODY) == request_hash(reordered)
    assert request_hash(BODY) != request_hash({**BODY, "model": "jev-1.15.0"})


def test_cached_judge_replays_a_stored_answer_across_instances(tmp_path):
    engine = open_database(tmp_path / "app.sqlite3")
    migrate(engine)
    calls = []

    def jev(body):
        calls.append(body)
        return RESPONSE

    assert CachedJudge(engine, jev)(BODY) == RESPONSE
    assert CachedJudge(engine, jev)(BODY) == RESPONSE
    assert len(calls) == 1
