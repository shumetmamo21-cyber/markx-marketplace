"""Anti-forgery protection on every request that changes data (blueprint H.2, H.3)."""

from __future__ import annotations

from tests.conftest import ApiClient, error_code

PHONE = "0911234567"


def test_a_request_without_the_client_header_is_refused() -> None:
    forged = ApiClient(send_client_header=False)
    response = forged.post("/auth/otp/request", json={"phone": PHONE})
    assert response.status_code == 403 and error_code(response) == "csrf_header_missing"


def test_reading_needs_no_client_header() -> None:
    assert ApiClient(send_client_header=False).get("/healthz").status_code == 200


def test_a_request_from_another_origin_is_refused(client: ApiClient) -> None:
    response = client.post(
        "/auth/otp/request", json={"phone": PHONE}, headers={"Origin": "https://evil.example"}
    )
    assert response.status_code == 403 and error_code(response) == "csrf_origin_mismatch"
    response = client.post(
        "/auth/otp/request", json={"phone": PHONE}, headers={"Sec-Fetch-Site": "cross-site"}
    )
    assert response.status_code == 403 and error_code(response) == "csrf_origin_mismatch"


def test_the_site_own_origin_is_accepted(client: ApiClient) -> None:
    response = client.post(
        "/auth/otp/request", json={"phone": PHONE}, headers={"Origin": "http://testserver"}
    )
    assert response.status_code == 200


def test_a_cookie_session_needs_the_csrf_token_to_change_data(client: ApiClient) -> None:
    client.sign_in(PHONE)
    without = ApiClient(send_csrf=False)
    without.http.cookies.set("markx_session", client.http.cookies.get("markx_session"))
    assert without.get("/me").status_code == 200  # reading is fine
    response = without.patch("/me", json={"name": "Mallory"})
    assert response.status_code == 403 and error_code(response) == "csrf_token_invalid"
    response = without.patch("/me", json={"name": "Mallory"}, headers={"X-CSRF-Token": "guess"})
    assert response.status_code == 403 and error_code(response) == "csrf_token_invalid"
    assert client.get("/me").json()["name"] is None

    # With the right token the same request succeeds.
    assert client.patch("/me", json={"name": "Abebe"}).status_code == 200


def test_one_session_csrf_token_does_not_work_for_another(client: ApiClient) -> None:
    client.sign_in(PHONE)
    other = ApiClient()
    other.sign_in("0922334455")
    response = other.patch(
        "/me", json={"name": "X"}, headers={"X-CSRF-Token": client.http.cookies.get("markx_csrf")}
    )
    assert response.status_code == 403 and error_code(response) == "csrf_token_invalid"


def test_a_cookie_token_is_not_accepted_as_a_bearer_token(client: ApiClient) -> None:
    client.sign_in(PHONE)
    token = client.http.cookies.get("markx_session")
    bare = ApiClient()
    response = bare.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_mini_app_sessions_travel_in_a_header_and_set_no_cookie() -> None:
    tma = ApiClient()
    tma.post("/auth/otp/request", json={"phone": PHONE}, headers={"X-MarkX-Client": "tma"})
    from tests.conftest import latest_code

    response = tma.post(
        "/auth/otp/verify",
        json={"phone": PHONE, "code": latest_code(PHONE)},
        headers={"X-MarkX-Client": "tma"},
    )
    assert response.status_code == 200
    token = response.json()["session_token"]
    assert token and "markx_session" not in response.headers.get("set-cookie", "")
    bearer = {"Authorization": f"Bearer {token}", "X-MarkX-Client": "tma"}
    assert ApiClient().get("/me", headers=bearer).status_code == 200
    # A header session is immune to cross-site forgery, so it needs no CSRF token.
    assert ApiClient(send_csrf=False).patch("/me", json={"name": "Tg"}, headers=bearer).status_code == 200
    # And it is not accepted as a cookie.
    as_cookie = ApiClient()
    as_cookie.http.cookies.set("markx_session", token)
    assert as_cookie.get("/me").status_code == 401
