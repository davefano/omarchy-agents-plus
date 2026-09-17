# Local Agents widget changes

The panel opens to a weekly overview grouped under company tabs: Anthropic for
Claude accounts, OpenAI for Codex accounts, and Fireworks when it has usage.
Tabs stay above the scrolling account list and detail view. Left/right (or h/l)
switch companies, up/down (or j/k) select an account, and Enter opens its details.
The detail dropdown only lists the selected company's accounts. Each company
remembers its selected account while the shell is running. Middle-clicking the
bar icon or calling the `next` IPC method also cycles companies.

Claude accounts use Fable weekly limits; other providers use their account-wide
weekly window. Rows open the full detail view with an account dropdown and a
return-to-overview button.

## Local reset times

Overview and detail views show reset calendar days and local wall-clock times,
for example `Resets tomorrow at 9 a.m. EDT`. The `reset_times.py` helper converts
each provider's offset-aware timestamp using the operating system's time zone
at the reset instant, so future daylight-saving transitions are handled too.
It runs on new usage data, when opening the panel, and every 30 seconds while
the panel is open. New processes pick up OS time-zone changes without restarting
the shell. Missing or offset-free timestamps stay unavailable; expired windows
retain their reset time and ask for a refresh.

Run `python3 -m unittest test_reset_times` for local midnight, source offsets,
time-zone changes, and both daylight-saving transition checks.

## Saved-login renewal

`Main.qml` invokes `refresh_usage.py` before collecting usage. It discovers extra
accounts through the installed Claude Accounts plugin and includes the default
`~/.claude` login. When an access token expires within two minutes, it runs Claude
Code's built-in `/usage` command in print mode. The CLI owns token refresh,
credential locking, and persistence; this helper never writes credential files.
Safe mode, empty settings sources, disabled tools/MCP, and no session persistence
keep this a usage check without project hooks or a model prompt.

Renewal attempts are serialized per account and have a five-minute cooldown.
Missing refresh tokens or unsuccessful renewals leave credentials intact and let
the existing collector report the authentication problem. Normal widget refresh
runs every 15 minutes; opening the panel or pressing R also runs this path.

Requires Claude Code with noninteractive `/usage` support (verified with the
installed 2.1.270). Ordinary `claude auth status` does not renew expired tokens.

Run `python3 test_refresh_usage.py` for the renewal regression checks.

## Extra Codex accounts

`refresh_usage.py` also invokes `codex_accounts.py`. It discovers saved logins
in `~/.codex-<name>/auth.json`, with separate records and caches per account.
Add a login with `codex-account work login`, then use it with `codex-account work`.
The login command refreshes the new panel record after sign-in. Browser login
must be completed by the account owner. The default `~/.codex` login stays on
the stock collector.

Custom labels or existing directories can be configured in
`~/.config/omarchy/agents/codex-accounts.json`:

```json
{"accounts": [{"id": "work", "name": "Codex · Work", "configDir": "~/.codex-work"}]}
```

An explicit account list replaces discovery; an empty list disables all extras.
Use `enabled: false` to disable an entry. Only this helper's records are pruned.
Run `python3 codex_accounts.py list` to inspect discovered accounts.

The adapter loads the installed Codex collector's native session parser and
app-server RPC. Extra-account stats exclude shared pi/OpenCode history, which
cannot reliably be attributed to a saved login. Native token history covers
session files touched within 30 days; account limits come from the server.
Usage on other machines requires the existing snapshot sync setup.

Run `python3 -m unittest test_codex_accounts test_refresh_usage` for checks.
Account directories follow the official OpenAI documentation:
https://learn.chatgpt.com/docs/auth and
https://learn.chatgpt.com/docs/config-file/config-advanced.
