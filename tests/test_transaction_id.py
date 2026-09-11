"""Tests B3: transaction id generator."""


from xactions.client import TwitterClient
from xactions.transaction_id import generate_transaction_id


def test_bound_mode_default_length_and_charset():
    tid = generate_transaction_id("GET", "/i/api/graphql/abc/UserByScreenName")
    assert 20 <= len(tid) <= 40
    assert all(c.isalnum() or c in "-_" for c in tid)


def test_bound_not_bare_uuid():
    tid = generate_transaction_id("POST", "/i/api/graphql/x/CreateTweet")
    assert tid.count("-") != 4  # not UUID form


def test_deterministic_inputs_change_output():
    a = generate_transaction_id("GET", "/a", now=1000.0)
    b = generate_transaction_id("GET", "/b", now=1000.0)
    assert a != b


def test_uuid_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("XACTIONS_TXID_MODE", "uuid")
    tid = generate_transaction_id("GET", "/")
    assert tid.count("-") == 4


def test_client_headers_include_txid():
    c = TwitterClient(cookies="auth_token=a; ct0=b")
    h = c._build_headers(method="POST", path="/i/api/graphql/x/CreateTweet")
    assert "x-client-transaction-id" in h
    assert h["x-client-transaction-id"]
    assert h["x-client-uuid"]
