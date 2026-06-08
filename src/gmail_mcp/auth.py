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
import json
import sys

from gmail_mcp.config import SCOPES, client_secret_path
from gmail_mcp.store import TokenStore


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
    print("Opening your browser to authorize a Gmail account...")
    creds = flow.run_local_server(port=0, prompt="consent")

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
