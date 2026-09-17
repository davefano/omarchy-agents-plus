# Working on My Agents

This repository is the source for the installed `davidfano.agents` Omarchy
plugin. The local installation can be a symlink to this checkout; edits may
reload the live desktop panel.

- Keep the manifest id stable so existing bar settings keep working.
- Keep all usage and authentication state outside the repository. Never add
  real account configuration, credentials, usage snapshots, or desktop captures.
- Read packaged Omarchy collectors and UI components as needed, but do not edit
  `/usr/share/omarchy`. Reuse the installed collectors through the adapters.
- Preserve per-account cache separation and the stock default account record.
- Run `python3 -m unittest discover -v` for Python changes. The tests use fake
  credentials and temporary directories, with no live provider requests.
- For QML changes, inspect the running panel and Quickshell logs. Test both
  company tabs and account details. A shell restart may be needed if plugin
  rescanning keeps an old QML component cached.
- Use `python3 scripts/install-local.py` to link a checkout into the local
  installation. It preserves previous files in a timestamped backup directory.

See README.md for setup and LOCAL-CHANGES.md for the behavior added to Omarchy.
