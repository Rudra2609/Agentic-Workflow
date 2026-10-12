"""Accounts over the real API: registration, sign-in, sessions, CSRF, password change and reset, rate limits."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from hmap.api.app import create_app
from hmap.services.accounts.security import token_hash
from hmap.system import HmapSystem
from tests.api.helpers import PASSWORD, CapturingMailer, second_client, signed_in, use_csrf


@pytest.fixture
def app_parts(tmp_path) -> Iterator[tuple[TestClient, HmapSystem, CapturingMailer]]:
    system = HmapSystem.in_memory(artifact_root=tmp_path / "a")
    mailer = CapturingMailer()
    with TestClient(create_app(system, run_agents=False, mailer=mailer)) as client:
        yield client, system, mailer


@pytest.fixture
def client(app_parts) -> TestClient:
    return app_parts[0]


def register(client: TestClient, email: str = "ada@example.test", password: str = PASSWORD, name: str = "Ada"):
    return client.post("/api/auth/register", json={"name": name, "email": email, "password": password})


def test_register_signs_in_with_secure_cookie_flags(client: TestClient) -> None:
    r = register(client, email="  Ada@Example.TEST ")
    assert r.status_code == 201
    user = r.json()["user"]
    assert user["email"] == "ada@example.test" and "password_hash" not in user and "password" not in r.text
    cookies = {c.split("=")[0]: c for c in r.headers.get_list("set-cookie")}
    assert "HttpOnly" in cookies["hmap_session"] and "SameSite=lax" in cookies["hmap_session"]
    assert "HttpOnly" not in cookies["hmap_csrf"] and "SameSite=strict" in cookies["hmap_csrf"]
    assert client.get("/api/auth/me").json()["user"]["user_id"] == user["user_id"]


@pytest.mark.parametrize(("body", "field", "status"), [
    ({"name": "", "email": "a@example.test", "password": PASSWORD}, "name", 400),
    ({"name": "A", "email": "not-an-email", "password": PASSWORD}, "email", 400),
    ({"name": "A", "email": "a@example.test", "password": "short"}, "password", 400),
    ({"name": "A", "email": "a@example.test", "password": "aaaaaaaaaaaa"}, "password", 400),
    ({"name": "Alexandra", "email": "a@example.test", "password": "alexandra-2026"}, "password", 400),
])
def test_registration_validation(client: TestClient, body, field, status) -> None:
    r = client.post("/api/auth/register", json=body)
    assert r.status_code == status and r.json()["detail"]["field"] == field


def test_duplicate_email_is_rejected_case_insensitively(client: TestClient) -> None:
    assert register(client).status_code == 201
    r = register(client, email="ADA@example.test")
    assert r.status_code == 409 and r.json()["detail"]["field"] == "email"


def test_login_logout_and_generic_errors(client: TestClient) -> None:
    register(client)
    client.cookies.clear()
    assert client.get("/api/auth/me").status_code == 401
    wrong = client.post("/api/auth/login", json={"email": "ada@example.test", "password": "wrong password!"})
    unknown = client.post("/api/auth/login", json={"email": "nobody@example.test", "password": PASSWORD})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == {"detail": "Email or password is incorrect."}   # no enumeration
    assert client.post("/api/auth/login", json={"email": "ADA@example.test", "password": PASSWORD}).status_code == 200
    use_csrf(client)
    token = client.cookies.get("hmap_session")
    assert client.post("/api/auth/logout").status_code == 204
    client.cookies.set("hmap_session", token)                      # replaying the old cookie must not work
    assert client.get("/api/auth/me").status_code == 401


def test_protected_routes_require_a_session(client: TestClient) -> None:
    for method, path in [("GET", "/api/projects"), ("POST", "/api/projects"), ("GET", "/api/agents"),
                         ("GET", "/api/events"), ("GET", "/api/dead-letters"), ("GET", "/api/tasks/T-x"),
                         ("GET", "/api/llm/usage"), ("POST", "/api/auth/ws-ticket")]:
        assert client.request(method, path, json={}).status_code == 401, path
    assert client.get("/api/health").status_code == 200                     # public: the sign-in page uses it


def test_state_changing_requests_need_the_csrf_header(client: TestClient) -> None:
    register(client)
    assert client.post("/api/projects", json={"name": "x"}).status_code == 403          # no header
    client.headers["X-CSRF-Token"] = "forged"
    assert client.post("/api/projects", json={"name": "x"}).status_code == 403          # wrong header
    use_csrf(client)
    assert client.post("/api/projects", json={"name": "x"}).status_code == 201
    assert client.get("/api/projects").status_code == 200                               # reads need none


def test_expired_session_is_rejected_and_removed(app_parts) -> None:
    client, system, _ = app_parts
    register(client)
    h = token_hash(client.cookies.get("hmap_session"))
    session = system.accounts._sessions[h]
    system.accounts._sessions[h] = session.model_copy(update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)})
    assert client.get("/api/auth/me").status_code == 401
    assert h not in system.accounts._sessions


def test_profile_update_and_password_change_end_other_sessions(app_parts) -> None:
    client, _system, _ = app_parts
    signed_in(client, email="ada@example.test")
    other = second_client(client)
    assert other.post("/api/auth/login", json={"email": "ada@example.test", "password": PASSWORD}).status_code == 200
    assert client.patch("/api/auth/me", json={"name": "Ada L."}).json()["user"]["name"] == "Ada L."
    bad = client.post("/api/auth/password", json={"current_password": "nope", "new_password": "new password 2026"})
    assert bad.status_code == 400 and bad.json()["detail"]["field"] == "current_password"
    r = client.post("/api/auth/password", json={"current_password": PASSWORD, "new_password": "new password 2026"})
    assert r.json() == {"other_sessions_ended": 1}
    assert client.get("/api/auth/me").status_code == 200                     # this session stays
    assert other.get("/api/auth/me").status_code == 401                      # the other one ended
    client.cookies.clear()
    assert client.post("/api/auth/login", json={"email": "ada@example.test",
                                                "password": "new password 2026"}).status_code == 200


def test_logout_everywhere(client: TestClient) -> None:
    signed_in(client, email="ada@example.test")
    other = second_client(client)
    other.post("/api/auth/login", json={"email": "ada@example.test", "password": PASSWORD})
    assert client.post("/api/auth/logout-all").status_code == 204
    assert other.get("/api/auth/me").status_code == 401 and client.get("/api/auth/me").status_code == 401


def test_password_reset_flow_is_single_use_and_does_not_enumerate(app_parts) -> None:
    client, _, mailer = app_parts
    signed_in(client, email="ada@example.test")
    known = client.post("/api/auth/forgot", json={"email": "ada@example.test"})
    unknown = client.post("/api/auth/forgot", json={"email": "ghost@example.test"})
    assert known.status_code == unknown.status_code == 202 and known.json() == unknown.json()
    assert [to for to, *_ in mailer.sent] == ["ada@example.test"]            # only real accounts get mail
    token = mailer.reset_token("ada@example.test")
    assert "?token" not in mailer.sent[0][2]                                 # fragment, not a query parameter

    weak = client.post("/api/auth/reset", json={"token": token, "password": "short"})
    assert weak.status_code == 400                                           # rejected before the token is spent
    assert client.post("/api/auth/reset", json={"token": token, "password": "brand new secret 1"}).status_code == 204
    assert client.post("/api/auth/reset", json={"token": token, "password": "another secret 22"}).status_code == 400
    assert client.get("/api/auth/me").status_code == 401                     # every session ended
    assert client.post("/api/auth/login", json={"email": "ada@example.test",
                                                "password": "brand new secret 1"}).status_code == 200
    assert client.post("/api/auth/reset", json={"token": "made-up", "password": "brand new secret 1"}).status_code \
        == 400


def test_expired_reset_token_is_refused(app_parts) -> None:
    client, system, mailer = app_parts
    signed_in(client, email="ada@example.test")
    client.post("/api/auth/forgot", json={"email": "ada@example.test"})
    token = mailer.reset_token("ada@example.test")
    h = token_hash(token)
    r = system.accounts._resets[h]
    system.accounts._resets[h] = r.model_copy(update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)})
    assert client.post("/api/auth/reset", json={"token": token, "password": "brand new secret 1"}).status_code == 400


def test_login_is_rate_limited(client: TestClient) -> None:
    register(client)
    codes = [client.post("/api/auth/login", json={"email": "ada@example.test", "password": "wrong guess!!"})
             .status_code for _ in range(11)]
    assert codes[:10] == [401] * 10 and codes[10] == 429
    blocked = client.post("/api/auth/login", json={"email": "ada@example.test", "password": PASSWORD})
    assert blocked.status_code == 429 and int(blocked.headers["Retry-After"]) > 0


def test_ws_ticket_is_single_use(client: TestClient) -> None:
    signed_in(client)
    client.post("/api/projects", json={"name": "something to stream"})
    ticket = client.post("/api/auth/ws-ticket").json()["ticket"]
    with client.websocket_connect(f"/api/ws/events?ticket={ticket}") as ws:
        assert "seq" in ws.receive_json()
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect), client.websocket_connect(f"/api/ws/events?ticket={ticket}") as ws:
        ws.receive_json()
    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/api/ws/events") as ws:
        ws.receive_json()


def test_ws_rejects_foreign_origins(client: TestClient) -> None:
    signed_in(client)
    ticket = client.post("/api/auth/ws-ticket").json()["ticket"]
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect), client.websocket_connect(
            f"/api/ws/events?ticket={ticket}", headers={"origin": "https://evil.example"}) as ws:
        ws.receive_json()
