"""OAuth bootstrap CLI for gmail-mcp.

The OAuth flow needs a browser, which an MCP tool can't drive cleanly, so
account authorization lives here as a console command rather than as an
MCP tool.

Commands::

    python -m gmail_mcp.auth add            # run the loopback OAuth flow
    python -m gmail_mcp.auth list           # list stored accounts
    python -m gmail_mcp.auth remove <email> # delete an account

Also installed as the ``gmail-mcp-auth`` console script.

The ``add`` command runs google-auth-oauthlib's InstalledAppFlow loopback
server, discovers the granted account's email via the Gmail profile
endpoint, and upserts the refresh token into the SQLite token store.
"""

from __future__ import annotations

import argparse
import errno
import json
import os
import socket
import subprocess
import sys
import time

from gmail_mcp.config import SCOPES, client_secret_path
from gmail_mcp.store import TokenStore


def _port_is_free(port: int) -> bool:
    """True if we can bind localhost:port right now (with address reuse)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _free_port(port: int) -> None:
    """Best-effort: kill whatever is holding the OAuth loopback port.

    A `gmail-mcp-auth add` attempt that never received its redirect (e.g. the
    SSH tunnel wasn't up yet) leaves a wsgiref listener squatting on the fixed
    port, so the next `add` dies with EADDRINUSE. The squatter is always our
    own orphaned auth flow, so killing it is safe. Tries `fuser`, falls back to
    `lsof`; both are best-effort and silently skipped if absent.
    """
    commands = (
        ["fuser", "-k", f"{port}/tcp"],
        ["sh", "-c", f"kill $(lsof -t -i:{port}) 2>/dev/null"],
    )
    for cmd in commands:
        try:
            subprocess.run(cmd, capture_output=True, timeout=5, check=False)
        except (FileNotFoundError, subprocess.SubprocessError):
            continue
        time.sleep(1)
        if _port_is_free(port):
            return


def _add() -> int:
    """Run the installed-app OAuth flow and store the resulting account."""
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    secret = client_secret_path()
    if not secret.exists():
        print(
            f"No OAuth client secret found at {secret}.\n"
            "Download a Google 'Desktop app' OAuth client JSON to that path "
            "(or set GMAIL_MCP_CLIENT_SECRET). See the README for setup steps.",
            file=sys.stderr,
        )
        return 1

    flow = InstalledAppFlow.from_client_secrets_file(str(secret), SCOPES)
    # Fixed port + no auto-launch: this server is headless. The flow prints an
    # auth URL you open in a browser on your own machine; the redirect comes
    # back to localhost:OAUTH_PORT, so SSH-forward that port (-L 8765:localhost:8765)
    # when authorizing remotely. Override with GMAIL_MCP_OAUTH_PORT.
    port = int(os.environ.get("GMAIL_MCP_OAUTH_PORT", "8765"))
    print(
        "\nAuthorize a Gmail account:\n"
        "  1. A URL will print below — open it in a browser signed into the "
        "account you want to add.\n"
        f"  2. After you approve, Google redirects to http://localhost:{port}/ .\n"
        f"     If you're SSH'd in, forward it: ssh -L {port}:localhost:{port} ...\n"
    )
    # The fixed port is often held by a prior `add` whose loopback listener is
    # still squatting (an attempt that never got its redirect). That bind fails
    # with EADDRINUSE. On collision we kill the squatter (always our own orphaned
    # auth flow) and retry, so back-to-back account adds just work.
    creds = None
    for attempt in range(1, 6):
        try:
            creds = flow.run_local_server(
                port=port, prompt="consent", open_browser=False
            )
            break
        except OSError as exc:
            if exc.errno != errno.EADDRINUSE or attempt == 5:
                raise
            print(
                f"Port {port} busy (orphaned listener from a prior add); "
                f"clearing it and retrying ({attempt}/4)...",
                file=sys.stderr,
            )
            _free_port(port)
            time.sleep(1)

    if not creds.refresh_token:
        print(
            "No refresh token returned. Revoke the app's access at "
            "https://myaccount.google.com/permissions and try again "
            "(the consent flow must re-prompt to issue a refresh token).",
            file=sys.stderr,
        )
        return 1

    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    profile = service.users().getProfile(userId="me").execute()
    email = profile["emailAddress"]

    store = TokenStore()
    store.upsert(
        email=email,
        refresh_token=creds.refresh_token,
        token=json.dumps({"access_token": creds.token}),
        scopes=" ".join(SCOPES),
    )
    print(f"Authorized and stored: {email}")
    print(f"Token store: {store.path}")
    return 0


def _list() -> int:
    store = TokenStore()
    accounts = store.list_accounts()
    if not accounts:
        print("No accounts stored yet. Run `gmail-mcp-auth add` to add one.")
        return 0
    print(f"{len(accounts)} account(s) in {store.path}:")
    for acct in accounts:
        last = acct.last_used_at or "never"
        print(f"  {acct.email}  (added {acct.added_at}, last used {last})")
    return 0


def _remove(email: str) -> int:
    store = TokenStore()
    if store.remove(email):
        print(f"Removed {email}.")
        return 0
    print(f"No stored account matching {email!r}.", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="gmail-mcp-auth",
        description="Manage Gmail accounts for the gmail-mcp server.",
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("add", help="authorize a new Gmail account via OAuth")
    sub.add_parser("list", help="list stored accounts")
    rm = sub.add_parser("remove", help="remove a stored account")
    rm.add_argument("email", help="email address of the account to remove")

    args = parser.parse_args(argv)

    if args.command == "add":
        return _add()
    if args.command == "list":
        return _list()
    if args.command == "remove":
        return _remove(args.email)
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
