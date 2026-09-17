# My Agents for Omarchy

A native Omarchy bar panel for AI account usage, with **Anthropic** and
**OpenAI** tabs, separate accounts, and reset times in your local time zone.
Built from Omarchy's Agents widget, with the custom behavior maintained here.

- Company tabs stay visible above the account list and detail view.
- Weekly allowance meters show each enabled account for the selected company.
- Reset labels say **Resets tomorrow at 9 a.m. EDT**. They follow the computer's
  time zone and the daylight-saving offset at the reset instant.
- Details show session limits, token history, and model usage.
- Extra Codex logins have separate records and caches. Extra Claude accounts
  integrate with the optional Claude Accounts plugin.
- Fireworks appears as another company when it has usage data.

## Requirements

An Omarchy desktop with its Quickshell UI and `omarchy-agent-usage-*` collectors,
Python 3.10 or later, and the CLI for each provider you use. No Python packages
need to be installed. Codex limits use the installed Codex app-server RPC.
Claude renewal requires a version supporting noninteractive `/usage`,
`--safe-mode`, and the other CLI flags in `refresh_usage.py`.

This plugin depends on the installed Omarchy collector and UI interfaces.

## Install from a working checkout

```bash
git clone https://github.com/davefano/omarchy-agents.git ~/workspaces/omarchy-agents
cd ~/workspaces/omarchy-agents
python3 scripts/install-local.py
omarchy plugin enable davidfano.agents
omarchy-shell shell rescanPlugins
```

The installer links `~/.config/omarchy/plugins/davidfano.agents` to the checkout
and `~/.local/bin/codex-account` to the included launcher. It saves previous
installations under `~/.local/state/omarchy/agents/backups/install-*`. Running it
again with the same checkout is safe. It honors `XDG_CONFIG_HOME` and
`XDG_STATE_HOME`; add `~/.local/bin` to your `PATH` if needed.

If the stock Agents widget is also enabled, disable that duplicate with
`omarchy plugin disable omarchy.agents`. If the shell shows an old version after
rescanning, run `omarchy restart shell`.

Edit the workspace files to develop the live widget. Keep the checkout at its
linked path, or rerun the installer after moving it.

## Add Codex accounts

Give each additional account a label and complete its browser login:

```bash
codex-account work login
codex-account personal login
```

Select the intended ChatGPT account in each browser login. To use one later:

```bash
codex-account work
```

Plain `codex` continues using the default login. The panel discovers extra
logins in `~/.codex-<label>/auth.json` and refreshes every 15 minutes by default.
Open the panel and press **R** to refresh immediately.

For custom names or existing directories, create
`~/.config/omarchy/agents/codex-accounts.json`:

```json
{
  "accounts": [
    {"id": "work", "name": "Codex · Work", "configDir": "~/.codex-work"},
    {"id": "personal", "name": "Codex · Personal", "configDir": "~/.codex-personal"}
  ]
}
```

An explicit account list replaces automatic discovery. Include every extra
account you want displayed, or set `enabled` to `false` to disable an entry.
Keep ids stable when changing display names. Credentials and this personal
configuration stay outside the repository.

Inspect discovery without contacting a provider:

```bash
python3 codex_accounts.py list
```

For extra Claude accounts, install
[Claude Accounts](https://github.com/leciric/omarchy-claude-multi-account-usage).
My Agents uses its discovery and collector when available.

## Controls

| Action | Control |
| --- | --- |
| Switch company | Click a tab or Left/Right (`h`/`l`) |
| Select an overview account | Up/Down (`k`/`j`) |
| Open details | Click a row or Enter |
| Change account in details | Account dropdown |
| Return to overview / close | Escape |
| Refresh usage | `r` |
| Cycle company from the bar | Middle-click |

IPC retains Omarchy's target: `omarchy-shell omarchy.agents open`, `close`,
`refresh`, or `next`.

## Data and limitations

Display records live in `~/.local/state/omarchy/agents/usage`. Account allowances
come from the providers; token history is local unless you configure snapshot
sync. Extra Codex accounts scan only their native sessions, excluding shared
pi/OpenCode history that cannot be attributed to an account. Native Codex scans
cover files touched in the last 30 days. Signing in does not import historical
usage from other machines.

Time conversion uses the computer's configured zone, not geolocation. It
refreshes on opening the panel, on new usage data, and every 30 seconds while
open. Expired reset timestamps stay marked as past due until fresh data arrives.

## Development and checks

```bash
python3 -m unittest discover -v
```

Tests use temporary files and fake credentials without provider requests.
For QML changes, check both tabs and account details on an Omarchy desktop,
then inspect `qs log -n -p /usr/share/omarchy/shell --no-color -t 30`.

See [LOCAL-CHANGES.md](LOCAL-CHANGES.md) for implementation notes and
[the original Agents README](docs/upstream-agents.md) for inherited record,
Fireworks, and snapshot-sync behavior. Its UI instructions describe the stock
widget; this README describes My Agents.

## License and origin

MIT. Derived from [Omarchy](https://github.com/omacom/omarchy), with its upstream
copyright notice retained in [LICENSE](LICENSE). The plugin id remains
`davidfano.agents` so existing local settings continue to work.
