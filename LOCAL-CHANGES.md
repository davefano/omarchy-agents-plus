# Local Agents widget changes

## Grok accounts

`grok_accounts.py` discovers the default Grok login and configured or discovered
extra login directories. It fetches account allowance and reset times from the
same billing endpoint as Grok Build's `/usage` screen, using each directory's
saved login. Responses are cached for 60 seconds; forced refresh bypasses the
cache. A directory or login change invalidates the cache. Transient errors label
the last successful reading as stale; authentication errors clear the meter and
ask for re-authentication. Usage records never include credentials or email.
The shared login registry uses `grok login` with `GROK_HOME` for
add-account and re-auth; `account_identity.py` reads the saved email locally.
When several distinct identities are saved in a folder, identity is reported
as ambiguous instead of selecting an arbitrary email. Grok accounts remain
visible without usage data. Daily token history is not yet connected. Account
settings and default Claude/Codex records remain separate.

## Account views

The panel opens to an overview grouped under company tabs: Anthropic for
Claude accounts, OpenAI for Codex accounts, xAI for Grok, and Fireworks when it has usage.
Tabs stay above the scrolling account list and detail view. Left/right (or h/l)
switch companies, up/down (or j/k) select an account, and Enter opens its details.
The detail dropdown only lists the selected company's accounts. Each company
remembers its selected account while the shell is running. Middle-clicking the
bar icon or calling the `next` IPC method also cycles companies.

The underlined **settings** link beside the account count replaces the old
"weekly allowance used" caption. `OverviewSettingsDialog.qml` offers a company's
reported limits and saves the selection in `overviewMetrics`, keyed by company.
It uses the same current persisted shell entry as account-name edits, preserving
other preferences across saves and plugin reloads. New installs default to overall
weekly usage; a saved Fable preference overrides that default. Every company with
accounts shows settings, including those with a single metric choice. A missing selected limit is labeled unavailable,
never replaced with a different meter. Rows open the full detail view with all
limits, an account dropdown, and a return-to-overview button.

`overviewSorts`, also keyed by company, stores default account order or ascending/
descending usage or reset time. Sorting uses the selected overview limit and
compares reset timestamps as instants. Unknown values stay last in both directions;
ties retain the original account order. The overview and account selector share
the sorted list, while the selected account stays pinned by id through a reorder.
Metric and sort changes are saved together without overwriting account names.

## Add-account dialog

The plus button beside the company tabs opens a provider/name form. The form
loads supported providers from `add_account.py`, which owns the login command
registry and launches the default terminal using argument arrays. Anthropic
uses `claude auth login` with an isolated `CLAUDE_CONFIG_DIR`; OpenAI uses
`codex login` with an isolated `CODEX_HOME` and file credential storage.
Inherited authentication overrides are removed from the login environment.
Sign-in runs in a private temporary directory outside account discovery. Only
a successful login is moved to its final directory; canceled or failed logins
cannot appear as accounts merely because the CLI wrote a partial credential file.

After successful authentication, the helper atomically saves the display name
to the provider's account configuration and refreshes that account through the
existing adapter. Existing discovered accounts, disabled entries, and unrelated
configuration keys are retained. A lock serializes form submissions, and
duplicate names, ids, directories, or existing credentials are rejected.
The Claude Accounts plugin remains required for extra Anthropic accounts.
The `codex-account` launcher also registers successful logins when an explicit
account list exists, so CLI additions continue to appear after using the form.

Run `python3 -m unittest test_add_account` for isolated login/registration tests.

## Account identity

Account details query `account_identity.py` for the selected login's email.
Anthropic uses the OAuth profile endpoint because `.claude.json` identity
metadata can refer to an older login, especially when default and explicit
`CLAUDE_CONFIG_DIR` layouts share credentials. Successful profile results are
cached privately for 15 minutes by directory and token fingerprint, and a
changed token invalidates the cached identity. OpenAI email is read locally
from the saved ID token. These values are display metadata only.

Only email/status reaches QML. Tokens never enter the usage records, identity
cache, or helper output; identity isn't included in synced usage snapshots.
An unavailable identity is shown explicitly instead of using another account
or stale Claude metadata. Requests finish asynchronously, and results remain
associated with their original account when the user switches details.
The displayed email stays visible during background checks. Identity lookups
run when changing accounts, entering details, manually refreshing, and every
30 seconds while details are open; usage-object rebuilds do not trigger them.

The underlined `re-auth` link beside the email uses the same provider command
registry as the add-account dialog. It passes the existing account id, display
name, and login folder to `add_account.py launch-reauth`. Default logins follow
the CLI's home environment variable; extra accounts require their own local
folder. The provider CLI handles sign-in in that folder without an initial
logout or rewriting account registration. Successful sign-ins refresh only
the selected account through the stock collector or its existing adapter.

The matching `edit` link opens `EditAccountDialog.qml` with the current name.
Saving merges a `providers.<account-id>.name` override into the existing plugin
settings through the shell's `updateEntryInline` API. It preserves other
provider options and account ids, including the stock default account. The
editor retains its original account id even if the selected account changes.
Both display and saving read the current entry from the shell's canonical
configuration. Omarchy can reinject an older bar-slot settings snapshot after
a plugin reload; that snapshot must not hide saved names or overwrite other
name overrides during the next edit. `test_account_settings.py` covers this
reload-and-edit sequence using the installed shell update API and a temporary
settings file (skipped when Omarchy/Wayland is unavailable).

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
