"""Server-layer tests: account validation and dispatch with a mocked client.

No live network calls — the Gmail service is replaced with a fake that
mimics the chained-builder API (users().messages().list().execute()).
"""

from __future__ import annotations

import base64

import pytest

import gmail_mcp.server as server
from gmail_mcp.store import TokenStore


@pytest.fixture
def store(tmp_path, monkeypatch):
    st = TokenStore(path=tmp_path / "tokens.db")
    monkeypatch.setattr(server, "_store", st)
    return st


def _b64url(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("utf-8")


# --- account validation -----------------------------------------------------

def test_require_account_unknown_lists_available(store):
    store.upsert("known@example.com", "r")
    with pytest.raises(ValueError) as exc:
        server._require_account("ghost@example.com")
    msg = str(exc.value)
    assert "ghost@example.com" in msg
    assert "known@example.com" in msg
    assert "gmail-mcp-auth add" in msg


def test_require_account_none_authorized(store):
    with pytest.raises(ValueError, match="none authorized yet"):
        server._require_account("x@example.com")


def test_require_account_ok(store):
    store.upsert("known@example.com", "r")
    acct = server._require_account("known@example.com")
    assert acct.email == "known@example.com"


# --- list_accounts dispatch -------------------------------------------------

def test_list_accounts_empty(store):
    out = server._dispatch("list_accounts", {})
    assert "No accounts authorized" in out


def test_list_accounts_nonempty(store):
    store.upsert("a@example.com", "r")
    out = server._dispatch("list_accounts", {})
    assert "a@example.com" in out
    assert "1 authorized account" in out


# --- mocked Gmail client ----------------------------------------------------

class FakeExec:
    def __init__(self, result):
        self._result = result

    def execute(self):
        return self._result


class FakeMessages:
    def __init__(self, recorder):
        self.r = recorder

    def list(self, **kw):
        self.r["list"] = kw
        return FakeExec({"messages": [{"id": "m1"}, {"id": "m2"}]})

    def get(self, **kw):
        self.r.setdefault("get", []).append(kw)
        if kw.get("format") == "metadata":
            return FakeExec({
                "id": kw["id"], "threadId": "t1", "snippet": "snip",
                "payload": {"headers": [
                    {"name": "From", "value": "a@b.com"},
                    {"name": "Subject", "value": f"subj-{kw['id']}"},
                ]},
            })
        return FakeExec({
            "id": kw["id"], "threadId": "t1",
            "payload": {
                "mimeType": "text/plain",
                "headers": [{"name": "Subject", "value": "Full"}],
                "body": {"data": _b64url("full body")},
            },
        })

    def modify(self, **kw):
        self.r["modify"] = kw
        return FakeExec({"id": kw["id"]})


class FakeLabels:
    def list(self, **kw):
        return FakeExec({"labels": [
            {"id": "INBOX", "name": "INBOX"},
            {"id": "Label_5", "name": "Receipts"},
        ]})


class FakeUsers:
    def __init__(self, recorder):
        self.r = recorder

    def messages(self):
        return FakeMessages(self.r)

    def labels(self):
        return FakeLabels()


class FakeService:
    def __init__(self):
        self.recorder = {}

    def users(self):
        return FakeUsers(self.recorder)


@pytest.fixture
def fake_service(store, monkeypatch):
    store.upsert("a@example.com", "refresh-token")
    svc = FakeService()
    # Bypass real credential building / network.
    monkeypatch.setattr(server, "_service_for", lambda email: svc)
    monkeypatch.setattr(server, "build_service", lambda acct, st: svc)
    return svc


def test_search_messages_dispatch(fake_service):
    out = server._dispatch("search_messages", {"account": "a@example.com", "query": "is:unread"})
    assert "2 message(s) in a@example.com" in out
    assert "subj-m1" in out
    assert fake_service.recorder["list"]["q"] == "is:unread"


def test_read_message_dispatch(fake_service):
    out = server._dispatch("read_message", {"account": "a@example.com", "message_id": "m1"})
    assert "full body" in out
    assert "Full" in out
    # Email content is wrapped in untrusted-data delimiters; the id is not.
    assert "UNTRUSTED EMAIL CONTENT" in out
    assert "Message m1" in out.split("UNTRUSTED EMAIL CONTENT")[0]


def test_send_is_gone():
    # send_message must be fully removed — no tool, no dispatch case.
    assert "Unknown tool" in server._dispatch("send_message", {})
    assert not hasattr(server, "_do_send")


def test_modify_labels_resolves_names(fake_service):
    out = server._dispatch("modify_labels", {
        "account": "a@example.com", "message_id": "m1", "add": ["Receipts"],
    })
    assert "Label_5" in out
    body = fake_service.recorder["modify"]["body"]
    assert body["addLabelIds"] == ["Label_5"]


def test_modify_labels_unknown_name(fake_service):
    with pytest.raises(ValueError, match="Unknown label"):
        server._dispatch("modify_labels", {
            "account": "a@example.com", "message_id": "m1", "add": ["DoesNotExist"],
        })


def test_modify_labels_noop(fake_service):
    out = server._dispatch("modify_labels", {"account": "a@example.com", "message_id": "m1"})
    assert "Nothing to do" in out


def test_list_labels_dispatch(fake_service):
    out = server._dispatch("list_labels", {"account": "a@example.com"})
    assert "Receipts" in out
    assert "Label_5" in out


def test_search_all_accounts(store, monkeypatch):
    store.upsert("a@example.com", "r")
    store.upsert("b@example.com", "r")
    svc = FakeService()
    monkeypatch.setattr(server, "build_service", lambda acct, st: svc)
    out = server._dispatch("search_all_accounts", {"query": "test"})
    assert "a@example.com" in out
    assert "b@example.com" in out
    assert "2 account(s)" in out


def test_search_all_accounts_none(store):
    out = server._dispatch("search_all_accounts", {"query": "test"})
    assert "No accounts authorized" in out


def test_unknown_tool():
    assert "Unknown tool" in server._dispatch("bogus", {})
