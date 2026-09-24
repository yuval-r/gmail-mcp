"""Token store CRUD against a temporary SQLite database."""

from __future__ import annotations

import pytest

from gmail_mcp.store import TokenStore


@pytest.fixture
def store(tmp_path):
    return TokenStore(path=tmp_path / "tokens.db")


def test_creates_db_and_dir(tmp_path):
    db = tmp_path / "nested" / "dir" / "tokens.db"
    TokenStore(path=db)
    assert db.exists()


def test_db_and_dir_are_owner_only(tmp_path):
    # The DB holds refresh tokens; nobody else on the machine may read it.
    db = tmp_path / "store" / "tokens.db"
    TokenStore(path=db)
    assert db.stat().st_mode & 0o777 == 0o600
    assert db.parent.stat().st_mode & 0o777 == 0o700


def test_existing_db_is_tightened(tmp_path):
    db = tmp_path / "tokens.db"
    TokenStore(path=db)
    db.chmod(0o644)
    TokenStore(path=db)
    assert db.stat().st_mode & 0o777 == 0o600


def _deny_chmod(monkeypatch):
    import gmail_mcp.store as store_mod

    def deny(path, mode):
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(store_mod.os, "chmod", deny)


def test_not_owned_but_private_db_still_opens(tmp_path, monkeypatch):
    # chmod fails on a file someone else owns; if it is already private, fine.
    db = tmp_path / "tokens.db"
    TokenStore(path=db)
    db.chmod(0o600)
    _deny_chmod(monkeypatch)
    TokenStore(path=db).list_accounts()


def test_not_owned_readable_db_is_refused(tmp_path, monkeypatch):
    # Refresh tokens readable by others, and no way to fix it: refuse.
    db = tmp_path / "tokens.db"
    TokenStore(path=db)
    db.chmod(0o644)
    _deny_chmod(monkeypatch)
    with pytest.raises(RuntimeError, match="0o644"):
        TokenStore(path=db)


def test_empty_list(store):
    assert store.list_accounts() == []
    assert store.get("nobody@example.com") is None


def test_upsert_and_get(store):
    store.upsert("a@example.com", "refresh-1", token='{"access_token": "x"}', scopes="s1 s2")
    acct = store.get("a@example.com")
    assert acct is not None
    assert acct.email == "a@example.com"
    assert acct.refresh_token == "refresh-1"
    assert acct.scopes == "s1 s2"
    assert acct.added_at is not None
    assert acct.last_used_at is None


def test_upsert_preserves_added_at(store):
    store.upsert("a@example.com", "refresh-1")
    first = store.get("a@example.com").added_at
    store.upsert("a@example.com", "refresh-2")
    second = store.get("a@example.com")
    assert second.refresh_token == "refresh-2"
    assert second.added_at == first  # added_at preserved across re-auth


def test_update_token(store):
    store.upsert("a@example.com", "refresh-1", token='{"access_token": "old"}')
    store.update_token("a@example.com", '{"access_token": "new"}')
    assert store.get("a@example.com").token == '{"access_token": "new"}'


def test_touch_sets_last_used(store):
    store.upsert("a@example.com", "refresh-1")
    assert store.get("a@example.com").last_used_at is None
    store.touch("a@example.com")
    assert store.get("a@example.com").last_used_at is not None


def test_list_sorted(store):
    store.upsert("b@example.com", "r")
    store.upsert("a@example.com", "r")
    emails = [a.email for a in store.list_accounts()]
    assert emails == ["a@example.com", "b@example.com"]


def test_remove(store):
    store.upsert("a@example.com", "r")
    assert store.remove("a@example.com") is True
    assert store.get("a@example.com") is None
    assert store.remove("a@example.com") is False
