# Gmail MCP — Development Guide

## What it is

A local stdio MCP server giving an AI agent unified access to **multiple
Gmail accounts at once**. The native Anthropic Gmail connector binds one
account per OAuth grant; this server holds refresh tokens for N accounts in
a local SQLite store and routes each tool call to the right inbox via an
`account` argument. `search_all_accounts` fans one query across every inbox.

## Layout

```
src/gmail_mcp/
  server.py   — MCP server entry point, tool registration, dispatch, per-account routing
  auth.py     — gmail-mcp-auth CLI: browser OAuth bootstrap (NOT an MCP tool)
  store.py    — SQLite token store (accounts table keyed by email)
  gmail.py    — per-account service build + token refresh; pure MIME parsing/formatting
  config.py   — path resolution (DB, client secret) + SCOPES constant
tests/        — pytest; Gmail client is mocked, no live network
```

## Module responsibilities

| Module | Purpose |
|--------|---------|
| `server.py` | Registers MCP tools, dispatches calls, resolves `account` → service. All Gmail network I/O runs in `asyncio.to_thread` (the google client is sync). |
| `auth.py` | `add` / `list` / `remove` subcommands. `add` runs `InstalledAppFlow.run_local_server`, reads the granted email from `users.getProfile`, upserts into the store. |
| `store.py` | `TokenStore` CRUD over `sqlite3`. `upsert` preserves `added_at`; `touch` stamps `last_used_at`; `update_token` persists refreshed access tokens. |
| `gmail.py` | `build_service(account, store)` builds google-auth `Credentials`, refreshes if stale, persists the new token, returns a Gmail client. Plus pure helpers — `parse_message`, `extract_body_and_attachments`, `strip_html`, `resolve_label_ids`, `build_mime_message`, formatters. |
| `config.py` | `db_path()`, `client_secret_path()`, `SCOPES`. |

## OAuth model

- **Auth is a CLI, not a tool** — the OAuth flow needs a browser, which an
  MCP tool can't drive. `gmail-mcp-auth add` runs the installed-app loopback
  flow and stores the refresh token.
- **Client config** comes from a downloaded Google "Desktop app" OAuth client
  JSON at `~/.gmail-mcp/client_secret.json` (env `GMAIL_MCP_CLIENT_SECRET`).
  Never hardcode `client_id`/`client_secret`.
- **Token store**: SQLite at `~/.gmail-mcp/tokens.db` (env `GMAIL_MCP_DB`).
  Keyed by email. Holds refresh_token + last access-token blob + scopes.
- **Refresh**: google-auth's `Request` transport refreshes the access token
  on demand; `build_service` persists the refreshed blob back to the DB.
- **Scopes** (one constant, `config.SCOPES`): `gmail.readonly`,
  `gmail.compose`, `gmail.modify`. Granular — NOT full `mail.google.com`,
  and **no `gmail.send`** (see Security model).

## Security model

- **No autonomous send.** There is no `send_message` tool and the `gmail.send`
  scope is not requested. The server can only `create_draft` — a draft sits in
  Gmail's drafts folder until the user sends it by hand, so an injected instruction
  can't exfiltrate mail. If send is ever wanted, it's a separate explicit
  decision; do not re-add it casually.
- **Email content is untrusted.** Sender, subject, snippet, body, and
  attachment filenames are attacker-controlled. Every tool returning email
  content wraps that region via `gmail.wrap_untrusted()` (delimiters:
  `⟦UNTRUSTED EMAIL CONTENT …⟧` / `⟦END UNTRUSTED EMAIL CONTENT⟧`). Ids
  (message/thread/label) stay OUTSIDE the wrapper so follow-up calls stay
  clean. Read-tool descriptions also carry `_UNTRUSTED_NOTICE` so the model is
  warned in-band. When adding a tool that surfaces message content, route it
  through the shared formatters / `wrap_untrusted`.
- **One fence per response, not per message.** Aggregators
  (`format_search_results`, `format_thread`) emit a single `wrap_untrusted`
  pair around the whole content blob and precede it with a TRUSTED `#N [id]
  (thread)` manifest; fenced bodies are keyed by the same `#N` ordinals. This
  cuts repeated-delimiter token overhead AND keeps real ids exclusively outside
  the fence (no genuine id inside for an attacker to mimic). Per-message
  `format_message_summary` / `format_parsed_message` still fence once each. The
  unwrapped inner content is built by `_summary_body` / `_parsed_body`; reuse
  those when adding an aggregator so the single-fence invariant holds.
- **Body length is capped.** `read_message` / `read_thread` truncate each body
  to `config.max_body_chars()` (env `GMAIL_MCP_MAX_BODY_CHARS`, default 20000,
  `<=0` = unlimited) via `gmail.truncate_body`, which appends a recoverable
  `… [truncated N chars — re-fetch with max_body_chars=0 …]` marker. Both tools
  accept a per-call `max_body_chars` arg (`_resolve_body_cap` resolves arg →
  config → unlimited). Search results are unaffected — they use Gmail's short
  `snippet`, not the full body.
- **`strip_html` is the HTML→text fallback** (used only when a message has no
  `text/plain` part). It strips comments (incl. Outlook `<!--[if mso]>` blocks
  whose `>` chars defeat a bare tag regex), `<head>`, and `<script>/<style>`,
  then decodes entities via the stdlib `html.unescape` (numeric + all named).
  Entity decoding runs AFTER tag removal so a decoded `<` can't be re-parsed as
  a tag — keep that ordering if you touch it.
- **No audit log** — intentionally not implemented.

## Gotchas

- **Refresh token only issues on first consent.** `add` passes
  `prompt="consent"` to force it. If a user already granted the app, Google
  may omit the refresh token; revoke at myaccount.google.com/permissions and
  re-run. `auth._add` errors clearly when no refresh token comes back.
- **Test-user / unverified-app expiry.** While the OAuth app is in "Testing",
  every account must be a listed test user, and refresh tokens expire after
  7 days. Publish the app for non-expiring tokens. See README.
- **Dead grant → `GmailAuthError`.** `build_service` raises it on refresh
  failure with a "re-run gmail-mcp-auth add" message; the server surfaces it.
- **`web` vs `installed` JSON section.** `_read_client_config` accepts either.
- **Sync client under async server.** Gmail API client is blocking; `call_tool`
  wraps `_dispatch` in `asyncio.to_thread`. Keep new tool logic in `_dispatch`
  (sync) so this holds.
- **Label resolution does not create labels.** `resolve_label_ids` matches
  existing ids/names (case-insensitive) and raises listing available names.

## Running tests

```bash
pip install -e ".[dev]"
pytest                  # unit tests, no network (Gmail client mocked)
ruff check src/ tests/  # lint
mypy src/               # type check
```
