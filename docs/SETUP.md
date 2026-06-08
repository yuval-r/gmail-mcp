# gmail-mcp setup — the no-brain version

Two parts: **(A)** get a `client_secret.json` from Google (one-time, in a web browser),
and **(B)** authorize each Gmail account on the server. You only do A once total;
you do B once per Gmail account.

---

## Part A — Get `client_secret.json` from Google Cloud

Do this in a normal web browser on your laptop. Sign in with **one** of your
Gmail accounts (doesn't matter which — this account just *owns* the project;
it can authorize any of your other accounts later).

1. Go to **https://console.cloud.google.com**
2. Top bar → the **project dropdown** (says "Select a project") → **New Project**.
   Name it `gmail-mcp` → **Create**. Wait a few seconds, then make sure that
   project is selected in the top bar.
3. Enable the API: go to **https://console.cloud.google.com/apis/library/gmail.googleapis.com**
   → big blue **Enable** button.
4. Set up the consent screen. Go to **APIs & Services → OAuth consent screen**
   (newer UI calls this **Google Auth Platform → Branding/Audience**).
   - User type: **External** → Create
   - App name: `gmail-mcp`. User support email: your email. Developer contact:
     your email. Save and continue through the screens.
   - **Scopes** screen: just click **Save and Continue** — don't add any here.
     (The app asks for its scopes at login time; you don't need to list them.)
   - **Test users** screen: click **Add Users** and add **every Gmail address
     you plan to connect**. Save and continue.
5. **Publish the app** (this is the important one). On the OAuth consent screen
   / **Audience** page, find **Publishing status: Testing** → click
   **PUBLISH APP** → confirm.
   - Why: in "Testing" mode Google **expires your login every 7 days** and
     you'd have to re-authorize weekly. Publishing makes it permanent.
   - It'll say the app is "unverified." That's fine — it's your own personal
     tool, only you log in. No verification needed for that.
6. Create the credential file. Go to **APIs & Services → Credentials** →
   **+ Create Credentials** → **OAuth client ID**.
   - Application type: **Desktop app**
   - Name: `gmail-mcp-desktop` → **Create**
   - A popup appears → click **Download JSON**. Save that file.

That downloaded `.json` is your `client_secret.json`.

---

## Part B — Put the secret on the server & authorize accounts

The server is headless, so the login happens in your laptop browser but the
"handshake" comes back to a port on the server. SSH forwarding bridges that.

1. **Put the secret in place** (on the server):
   ```bash
   mkdir -p ~/.gmail-mcp
   # copy the downloaded file there, renamed exactly:
   mv ~/whatever-google-named-it.json ~/.gmail-mcp/client_secret.json
   ```
   (From your laptop you can scp it:
   `scp ~/Downloads/client_secret_*.json kc@superhellfirejr:~/.gmail-mcp/client_secret.json`)

2. **SSH in with the port forwarded:**
   ```bash
   ssh -L 8765:localhost:8765 kc@superhellfirejr
   ```

3. **Authorize an account:**
   ```bash
   /mnt/x/code/gmail-mcp/.venv/bin/gmail-mcp-auth add
   ```
   It prints a long `https://accounts.google.com/...` URL. **Copy it, paste it
   into a browser on your laptop that's signed into the Gmail account you want
   to add.** Approve the access ("unverified app" → Advanced → Go to gmail-mcp).
   The browser will land on a "The authentication flow has completed" page and
   the command will print `Authorized and stored: you@gmail.com`.

4. **Repeat step 3 for each account.** To add a second account, either use a
   different browser/profile or sign that browser into the other account first,
   then run `gmail-mcp-auth add` again.

5. **Confirm:**
   ```bash
   /mnt/x/code/gmail-mcp/.venv/bin/gmail-mcp-auth list
   ```
   You should see every account listed.

That's it. The MCP server reads those stored tokens — no further login needed.
To remove an account later: `gmail-mcp-auth remove you@gmail.com`.
