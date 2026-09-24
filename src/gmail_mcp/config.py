"""Configuration and path resolution for gmail-mcp.

Resolves the on-disk locations the server and auth CLI need:

  * The token database (SQLite) — default ``~/.gmail-mcp/tokens.db``,
    overridable via the ``GMAIL_MCP_DB`` environment variable.
  * The Google OAuth "Desktop app" client-secret JSON — default
    ``~/.gmail-mcp/client_secret.json``, overridable via the
    ``GMAIL_MCP_CLIENT_SECRET`` environment variable.
  * The attachment download root, default ``~/.gmail-mcp/attachments``,
    overridable via the ``GMAIL_MCP_ATTACHMENT_DIR`` environment variable.
    Downloads land in its ``quarantine/`` subdirectory first.
  * The virus-scanner command, ``GMAIL_MCP_SCAN_CMD``, or ClamAV's
    ``clamscan`` when it is installed.

No secrets are hardcoded here. The client_id / client_secret are read
from the client-secret JSON you download from the Google Cloud Console.
"""

from __future__ import annotations

import os
import shlex
import shutil
from pathlib import Path

# OAuth scopes. Granular — read, compose drafts, modify labels, and manage
# filters/settings. NOT the full https://mail.google.com/ scope. gmail.send is
# intentionally NOT requested: this server never sends mail autonomously, it
# only creates drafts that you send by hand (prompt-injection safety).
#
# gmail.settings.basic backs the filter tools (list/create/delete_filter). It
# permits filter management but NOT forwarding-address changes (that needs
# gmail.settings.sharing, which we deliberately do not request) — so a filter
# created here can label/archive/trash mail but can never forward it off-account.
SCOPES: list[str] = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.settings.basic",
]

_DEFAULT_DIR = Path.home() / ".gmail-mcp"

# Per-message body cap, in characters, applied when surfacing parsed message
# bodies (read_message / read_thread). Long marketing mail and quoted threads
# are the dominant token cost; capping keeps a single read from flooding the
# model's context. The default is deliberately tight (~500 chars ≈ 125 tokens —
# enough to triage the gist) so reads are cheap by default and the agent opts
# into a full body explicitly. 0 or negative ⇒ unlimited. A caller can override
# per-request, and re-fetch in full by passing max_body_chars=0.
_DEFAULT_MAX_BODY_CHARS = 500

# Hard ceiling on a single downloaded attachment, in bytes. Gmail's own
# attachment limit is 25 MB, so this refuses nothing Gmail would deliver; it
# exists so a malformed or hostile size can't be decoded into memory unbounded.
_DEFAULT_MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024


def db_path() -> Path:
    """Path to the SQLite token store.

    Honors ``GMAIL_MCP_DB``; defaults to ``~/.gmail-mcp/tokens.db``.
    """
    override = os.environ.get("GMAIL_MCP_DB")
    if override:
        return Path(override).expanduser()
    return _DEFAULT_DIR / "tokens.db"


def client_secret_path() -> Path:
    """Path to the Google OAuth client-secret JSON.

    Honors ``GMAIL_MCP_CLIENT_SECRET``; defaults to
    ``~/.gmail-mcp/client_secret.json``.
    """
    override = os.environ.get("GMAIL_MCP_CLIENT_SECRET")
    if override:
        return Path(override).expanduser()
    return _DEFAULT_DIR / "client_secret.json"


def max_body_chars() -> int:
    """Default per-message body cap in characters.

    Honors ``GMAIL_MCP_MAX_BODY_CHARS``; defaults to
    ``_DEFAULT_MAX_BODY_CHARS``. A value <= 0 means unlimited. A malformed
    value falls back to the default rather than crashing the server.
    """
    raw = os.environ.get("GMAIL_MCP_MAX_BODY_CHARS")
    if raw is None:
        return _DEFAULT_MAX_BODY_CHARS
    try:
        return int(raw)
    except ValueError:
        return _DEFAULT_MAX_BODY_CHARS


def attachments_dir() -> Path:
    """Root directory attachments are downloaded into.

    Honors ``GMAIL_MCP_ATTACHMENT_DIR``; defaults to
    ``~/.gmail-mcp/attachments``. Downloads are confined to a per-message
    subdirectory of this root, and the root is the ONLY writable location the
    server has. There is deliberately no per-call destination argument, because
    that would be an arbitrary-file-write primitive reachable by an instruction
    embedded in an email.
    """
    override = os.environ.get("GMAIL_MCP_ATTACHMENT_DIR")
    if override:
        return Path(override).expanduser()
    return _DEFAULT_DIR / "attachments"


def quarantine_dir() -> Path:
    """Where downloads are written before a virus scan releases them.

    Lives under the attachment root, so the one-root containment check still
    covers it. Message ids are hex, so no per-message directory can collide
    with the name ``quarantine``.
    """
    return attachments_dir() / "quarantine"


# Homebrew's bin dirs are not always on the PATH an MCP client gives a server.
_CLAMSCAN_FALLBACKS = ("/opt/homebrew/bin/clamscan", "/usr/local/bin/clamscan")


def scan_command() -> list[str] | None:
    """Argv of the virus scanner run on quarantined downloads, or None.

    Honors ``GMAIL_MCP_SCAN_CMD`` (split like a shell command; an empty value
    turns scanning off). Otherwise uses ClamAV's ``clamscan`` if it is
    installed. The file paths to scan are appended to the argv. The scanner
    must follow the ClamAV exit-code convention: 0 clean, 1 threat found,
    anything else an error.
    """
    raw = os.environ.get("GMAIL_MCP_SCAN_CMD")
    if raw is not None:
        return shlex.split(raw) or None
    found = shutil.which("clamscan") or next(
        (p for p in _CLAMSCAN_FALLBACKS if os.access(p, os.X_OK)), None
    )
    if found is None:
        return None
    return [found, "--no-summary", "--infected", "--stdout"]


def max_attachment_bytes() -> int:
    """Per-attachment size ceiling in bytes.

    Honors ``GMAIL_MCP_MAX_ATTACHMENT_BYTES``; defaults to 25 MB. A value <= 0
    means unlimited. A malformed value falls back to the default rather than
    crashing the server.
    """
    raw = os.environ.get("GMAIL_MCP_MAX_ATTACHMENT_BYTES")
    if raw is None:
        return _DEFAULT_MAX_ATTACHMENT_BYTES
    try:
        return int(raw)
    except ValueError:
        return _DEFAULT_MAX_ATTACHMENT_BYTES
