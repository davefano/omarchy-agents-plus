import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

Panel {
  id: root
  moduleName: "omarchy.agents"
  ipcTarget: "omarchy.agents"
  manageIpc: false

  readonly property color foreground: bar ? bar.foreground : Color.foreground
  readonly property color urgent: bar ? bar.urgent : Color.urgent
  readonly property color dim: Qt.darker(foreground, 1.55)
  readonly property color surface: Color.popups.background
  readonly property color track: Style.selectedFillFor(foreground, Color.accent)
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family

  // Omarchy can reinject a ModuleSlot's original settings after plugin reloads.
  // Read the current shell entry for display and edits so that stale snapshot
  // cannot hide saved names or overwrite them on the next save.
  readonly property var persistedSettings: {
    var host = root.bar && root.bar.shell ? root.bar.shell : null
    var config = host && "shellConfig" in host ? host.shellConfig : null
    if (!config) return root.settings
    var layout = config.bar && config.bar.layout ? config.bar.layout : {}
    var groups = [layout.left || [], layout.center || [], layout.right || [], config.plugins || []]
    var target = Util.canonicalWidgetId(root.moduleName)
    for (var g = 0; g < groups.length; g++) {
      for (var i = 0; i < groups[g].length; i++) {
        var entry = groups[g][i]
        if (entry && Util.canonicalWidgetId(String(entry.id || "")) === target) return entry
      }
    }
    return root.settings
  }

  readonly property var allAccounts: usage.enabledProviders
  readonly property var companies: {
    var result = []
    var seen = {}
    for (var i = 0; i < allAccounts.length; i++) {
      var company = companyForAccount(allAccounts[i])
      if (seen[company.value]) continue
      seen[company.value] = true
      result.push(company)
    }
    var order = ["anthropic", "openai", "xai", "fireworks"]
    return result.sort(function(a, b) {
      var ai = order.indexOf(a.value), bi = order.indexOf(b.value)
      return (ai < 0 ? order.length : ai) - (bi < 0 ? order.length : bi)
        || a.label.localeCompare(b.label)
    })
  }
  property string selectedCompanyId: "anthropic"
  readonly property int companyIndex: {
    for (var i = 0; i < companies.length; i++)
      if (companies[i].value === selectedCompanyId) return i
    return 0
  }
  readonly property string companyId: companies.length > 0 ? companies[companyIndex].value : ""
  readonly property string companyName: companies.length > 0 ? companies[companyIndex].label : ""
  readonly property var providers: sortAccounts(allAccounts.filter(function(account) {
    return companyForAccount(account).value === companyId
  }), overviewSort(companyId))
  // Keep each company's selected account stable across refreshes and tab changes.
  property var selectedAccountIds: ({})
  readonly property string selectedProviderId: selectedAccountIds[companyId] || ""
  readonly property int providerIndex: {
    for (var i = 0; i < providers.length; i++)
      if (providers[i].providerId === selectedProviderId) return i
    return 0
  }
  readonly property var provider: providers.length > 0 ? providers[providerIndex] : null

  property bool cursorActive: false
  property bool overview: true
  onOverviewChanged: {
    if (panelFlick) panelFlick.contentY = 0
    Qt.callLater(refreshIdentity)
  }

  property var accountIdentity: null
  property bool identityRefreshPending: false
  readonly property string identityKey: provider ? provider.providerId + "\n" + provider.configDir : ""
  readonly property string identityText: {
    if (!accountIdentity || accountIdentity.key !== identityKey) return "Checking account email…"
    return accountIdentity.email || accountIdentity.status || "Email unavailable"
  }
  // Usage rebuilds provider objects even when the selected login is unchanged.
  // Only selection changes should trigger another immediate identity lookup.
  onIdentityKeyChanged: {
    reauthError = ""
    Qt.callLater(refreshIdentity)
  }

  property string reauthError: ""
  readonly property bool canReauthenticate: !!provider
    && (companyId === "anthropic" || companyId === "openai" || companyId === "xai")
    && (provider.providerId === "claude" || provider.providerId === "codex"
      || provider.providerId === "grok" || provider.configDir !== "")

  function reauthenticate() {
    if (!canReauthenticate || reauthLauncher.running) return
    reauthError = ""
    reauthLauncher.requestKey = identityKey
    reauthLauncher.command = ["python3",
      decodeURIComponent(String(Qt.resolvedUrl("add_account.py")).replace(/^file:\/\//, "")),
      "launch-reauth", "--", companyId, provider.providerName, provider.providerId, provider.configDir]
    reauthLauncher.running = true
  }

  function refreshIdentity() {
    if (!opened || overview || !provider) return
    if (identityProcess.running) {
      identityRefreshPending = true
      return
    }
    // Keep the current email visible until its replacement arrives. identityKey
    // already prevents showing it for a different account.
    identityProcess.requestKey = identityKey
    identityProcess.command = ["python3",
      decodeURIComponent(String(Qt.resolvedUrl("account_identity.py")).replace(/^file:\/\//, "")),
      "--", provider.providerId, provider.configDir]
    identityProcess.running = true
  }

  function renameAccount(accountId, name) {
    name = name.trim()
    if (!name || name.length > 80 || /[\x00-\x1f\x7f]/.test(name))
      return "Enter a name of 1–80 characters on one line."
    if (!root.bar || !root.bar.shell || typeof root.bar.shell.updateEntryInline !== "function")
      return "Account settings are unavailable. Please reopen the panel."
    var next = Object.assign({}, root.persistedSettings)
    next.providers = Object.assign({}, next.providers || {})
    var previous = next.providers[accountId] || {}
    if (previous.name === name) return ""
    next.providers[accountId] = Object.assign({}, previous, { name: name })
    if (!root.bar.shell.updateEntryInline(root.moduleName, next))
      return "Unable to save the account name. Please reopen the panel."
    root.settings = next
    return ""
  }

  component AccountLink: AbstractButton {
    id: link
    implicitWidth: contentItem.implicitWidth
    implicitHeight: contentItem.implicitHeight
    padding: 0
    opacity: enabled ? 1 : 0.5
    contentItem: Text {
      text: link.text
      color: link.hovered || link.activeFocus ? Color.accent : root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
      font.underline: true
    }
    HoverHandler { cursorShape: Qt.PointingHandCursor }
  }

  // Refresh calendar labels while the panel is open, including across midnight.
  property double nowMs: Date.now()
  property var resetLabels: ({})
  property bool resetRefreshPending: false
  readonly property var resetTimestamps: {
    var timestamps = []
    for (var i = 0; i < allAccounts.length; i++) {
      var windows = allAccounts[i].limits || []
      for (var j = 0; j < windows.length; j++) {
        var timestamp = String(windows[j].resetsAt || "")
        if (timestamp !== "" && timestamps.indexOf(timestamp) < 0) timestamps.push(timestamp)
      }
    }
    return timestamps
  }
  onResetTimestampsChanged: Qt.callLater(refreshResetLabels)

  readonly property var limits: limitWindows(provider)
  readonly property var models: modelRows(provider)
  readonly property var headline: bindingWindow(provider)
  readonly property var balance: provider ? (provider.balance || null) : null
  // A prepaid account runs low the way a subscription window fills up: the
  // last 10% of the funded credits lights the same alarm.
  readonly property bool balanceAlarming: !!balance && balance.funded > 0
    && balance.remaining / balance.funded <= 0.1
  readonly property bool alarming: (!!headline && headline.percent >= 0.9) || balanceAlarming

  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)) }
  function alpha(c, a) { return Qt.rgba(c.r, c.g, c.b, a) }

  function companyForAccount(account) {
    if (!account) return { value: "", label: "" }
    var id = String(account.providerId || "")
    if (/^claude(?:-|$)/.test(id)) return { value: "anthropic", label: "Anthropic" }
    if (/^codex(?:-|$)/.test(id)) return { value: "openai", label: "OpenAI" }
    if (/^grok(?:-|$)/.test(id)) return { value: "xai", label: "xAI" }
    if (/^fireworks(?:-|$)/.test(id)) return { value: "fireworks", label: "Fireworks" }
    return { value: id, label: String(account.providerName || id) }
  }

  function selectCompany(index) {
    if (companies.length === 0) return
    var wrapped = ((index % companies.length) + companies.length) % companies.length
    if (companies[wrapped].value === companyId) return
    accountSelector.close()
    selectedCompanyId = companies[wrapped].value
    overview = true
    cursorActive = false
    panelFlick.contentY = 0
    keyCatcher.forceActiveFocus()
  }

  function selectProvider(index) {
    if (providers.length === 0) return
    var wrapped = ((index % providers.length) + providers.length) % providers.length
    var selections = Object.assign({}, selectedAccountIds)
    selections[companyId] = providers[wrapped].providerId
    selectedAccountIds = selections
  }

  function showDetails(index) {
    selectProvider(index)
    overview = false
    keyCatcher.forceActiveFocus()
  }

  function showOverview() {
    accountSelector.close()
    overview = true
    keyCatcher.forceActiveFocus()
  }

  function metricKey(label) {
    var key = String(label || "").trim().toLowerCase()
    if (/^(weekly(?: \(7-day\))?|7[- ]day(?: window)?|7d(?: window)?|week)$/.test(key)) return "weekly"
    return key
  }

  function overviewMetric(company) {
    var choices = root.persistedSettings.overviewMetrics || {}
    return String(choices[company] || "weekly")
  }

  readonly property var sortOptions: [
    { value: "default", label: "Default account order" },
    { value: "usage-asc", label: "Usage: least used first" },
    { value: "usage-desc", label: "Usage: most used first" },
    { value: "reset-asc", label: "Reset: soonest first" },
    { value: "reset-desc", label: "Reset: latest first" }
  ]

  function overviewSort(company) {
    var sorts = root.persistedSettings.overviewSorts || {}
    return String(sorts[company] || "default")
  }

  function sortAccounts(accounts, mode) {
    if (mode === "default") return accounts
    var byReset = mode === "reset-asc" || mode === "reset-desc"
    var descending = mode === "usage-desc" || mode === "reset-desc"
    // Read each selected window once. Original positions break ties so equal
    // percentages don't shuffle accounts on every refresh; unknowns stay last.
    return accounts.map(function(account, index) {
      var window = overviewWindow(account)
      var value = window ? (byReset ? Date.parse(window.resetAt) : window.percent) : NaN
      return { account: account, index: index, value: value }
    }).sort(function(a, b) {
      var aKnown = isFinite(a.value), bKnown = isFinite(b.value)
      if (aKnown !== bKnown) return aKnown ? -1 : 1
      if (!aKnown || a.value === b.value) return a.index - b.index
      return (a.value - b.value) * (descending ? -1 : 1)
    }).map(function(row) { return row.account })
  }

  function metricLabel(key) {
    if (key === "weekly") return "Overall weekly usage"
    if (key === "fable weekly") return "Fable weekly usage"
    if (key === "session (5-hour)") return "Session usage (5-hour)"
    return key.charAt(0).toUpperCase() + key.slice(1)
  }

  function metricOptions(company) {
    var seen = {}
    var result = []
    allAccounts.forEach(function(account) {
      if (companyForAccount(account).value !== company) return
      var limits = account.limits || []
      limits.forEach(function(entry) {
        var key = metricKey(entry.label)
        if (!key || seen[key]) return
        seen[key] = true
        result.push({value: key, label: metricLabel(key)})
      })
    })
    // Keep a saved selection reachable if an account stops reporting that limit.
    var selected = overviewMetric(company)
    if (!seen[selected]) result.push({value: selected, label: metricLabel(selected)})
    var order = ["weekly", "fable weekly", "session (5-hour)"]
    return result.sort(function(a, b) {
      var ai = order.indexOf(a.value), bi = order.indexOf(b.value)
      return (ai < 0 ? order.length : ai) - (bi < 0 ? order.length : bi) || a.label.localeCompare(b.label)
    })
  }

  readonly property var overviewOptions: metricOptions(companyId)
  readonly property string overviewHeading: metricLabel(overviewMetric(companyId)).replace(/ usage(?: \(5-hour\))?$/, "") + " limits"

  function saveOverviewSettings(company, metric, sort) {
    sort = sort || overviewSort(company)
    if (!metricOptions(company).some(function(option) { return option.value === metric }))
      return "Choose an available usage limit."
    if (!sortOptions.some(function(option) { return option.value === sort }))
      return "Choose an available sort order."
    if (!root.bar || !root.bar.shell || typeof root.bar.shell.updateEntryInline !== "function")
      return "Settings are unavailable. Please reopen the panel."
    var next = Object.assign({}, root.persistedSettings)
    next.overviewMetrics = Object.assign({}, next.overviewMetrics || {})
    next.overviewMetrics[company] = metric
    next.overviewSorts = Object.assign({}, next.overviewSorts || {})
    next.overviewSorts[company] = sort
    var selected = provider ? provider.providerId : ""
    if (!root.bar.shell.updateEntryInline(root.moduleName, next))
      return "Unable to save settings. Please try again."
    root.settings = next
    // A new order must not silently switch the selected account.
    if (selected) {
      var selections = Object.assign({}, selectedAccountIds)
      selections[companyId] = selected
      selectedAccountIds = selections
    }
    return ""
  }

  function openOverviewSettings() {
    overviewSettingsDialog.open(companyId, companyName, overviewOptions, overviewMetric(companyId), overviewSort(companyId))
  }

  function overviewWindow(p) {
    var selected = overviewMetric(companyForAccount(p).value)
    var entries = p ? (p.limits || []) : []
    for (var i = 0; i < entries.length; i++) {
      var entry = entries[i] || {}
      if (metricKey(entry.label) !== selected) continue
      if (entry.percent === null || entry.percent === undefined || entry.percent === "") continue
      var percent = Number(entry.percent)
      if (!isFinite(percent) || percent < 0) continue
      return { percent: percent, resetAt: String(entry.resetsAt || "") }
    }
    return null
  }

  function overviewResetText(p, window) {
    var label = metricLabel(overviewMetric(companyForAccount(p).value))
    return window ? label.replace(/ usage$/, "") + " · " + resetLabel(window) : label + " unavailable"
  }

  function moveOverviewCursor(delta) {
    cursorActive = true
    selectProvider(providerIndex + delta)
    var row = overviewRows.itemAt(providerIndex)
    if (!row) return
    var top = row.mapToItem(column, 0, 0).y
    if (top < panelFlick.contentY) panelFlick.contentY = top
    else if (top + row.height > panelFlick.contentY + panelFlick.height)
      panelFlick.contentY = top + row.height - panelFlick.height
  }

  function refreshNow() {
    usage.refreshAll(true)
    refreshIdentity()
  }

  function launchAgent() {
    if (root.bar) root.bar.run("omarchy-agent --pick")
    root.close()
  }

  // ---------------------------------------------------------------- limits
  //
  // Both providers report the same two shapes: a short rolling session window
  // and a long weekly one. Everything below normalizes them into one record so
  // the meters and the hero speak a single language.

  // Claude spells its windows out ("Session (5-hour)"), Codex abbreviates
  // them ("5h window", "30m window"). Both have to land on the same record.
  function windowIsLong(text) {
    return text.indexOf("week") >= 0 || text.indexOf("7-day") >= 0 || text.indexOf("seven") >= 0
      || text.indexOf("month") >= 0 || text.indexOf("30-day") >= 0
  }

  function windowSpanMs(label) {
    var text = String(label || "").toLowerCase()
    if (text.indexOf("month") >= 0 || text.indexOf("30-day") >= 0) return 30 * 24 * 3600 * 1000
    if (windowIsLong(text)) return 7 * 24 * 3600 * 1000
    var hours = text.match(/(\d+)\s*-?\s*h(?:our)?\b/)
    if (hours) return Number(hours[1]) * 3600 * 1000
    var minutes = text.match(/(\d+)\s*-?\s*m(?:in(?:ute)?s?)?\b/)
    if (minutes) return Number(minutes[1]) * 60 * 1000
    return 0
  }

  function windowTitle(label) {
    var text = String(label || "").toLowerCase()
    if (text.indexOf("month") >= 0) return "Monthly"
    if (windowIsLong(text)) return "Weekly"
    if (text.indexOf("session") >= 0 || windowSpanMs(label) > 0) return "Session"
    var plain = String(label || "").replace(/\s*\(.*\)\s*/, "").trim()
    return plain === "" ? "Limit" : plain
  }

  // A collector that already knows which window a limit belongs to says so,
  // and that beats reading it back out of the label: a model-scoped limit is
  // titled after its model, and a name like "Opus 5 (1M context)" would parse
  // as a one-minute window.
  function limitWindow(label, percent, resetAt, title) {
    return {
      title: String(title || "") !== "" ? String(title) : windowTitle(label),
      percent: Number(percent),
      resetAt: String(resetAt || "")
    }
  }

  function limitWindows(p) {
    if (!p) return []
    var out = []
    var list = p.limits || []
    for (var i = 0; i < list.length; i++) {
      var entry = list[i] || {}
      var percent = Number(entry.percent)
      if (percent >= 0) out.push(limitWindow(entry.label, percent, entry.resetsAt, entry.title))
    }
    return out
  }

  // The window that decides how much room is left — the fullest one, since
  // that is what stops the next prompt.
  function bindingWindow(p) {
    var windows = limitWindows(p)
    var best = null
    for (var i = 0; i < windows.length; i++) {
      if (!best || windows[i].percent > best.percent) best = windows[i]
    }
    return best
  }

  function resetLabel(window) {
    return window && resetLabels[window.resetAt]
      ? resetLabels[window.resetAt] : "Reset time unavailable"
  }

  function refreshResetLabels() {
    if (resetLabelProcess.running) {
      resetRefreshPending = true
      return
    }
    var helper = decodeURIComponent(String(Qt.resolvedUrl("reset_times.py")).replace(/^file:\/\//, ""))
    resetLabelProcess.command = ["python3", helper, JSON.stringify(resetTimestamps)]
    resetLabelProcess.running = true
  }

  // ---------------------------------------------------------------- balance
  //
  // Prepaid agents report a credit ledger instead of rate-limit windows: the
  // record's balance object carries remaining, funded, and spent amounts.

  function currencyPrefix(currency) {
    var code = String(currency || "USD").toUpperCase()
    if (code === "USD") return "$"
    if (code === "EUR") return "€"
    if (code === "GBP") return "£"
    return code + " "
  }

  function formatMoney(value, currency) {
    var amount = Number(value)
    if (!isFinite(amount)) amount = 0
    return currencyPrefix(currency) + amount.toFixed(2)
  }

  function balanceDetailText(b) {
    if (!b || !(b.funded > 0)) return ""
    var text = formatMoney(b.spent, b.currency) + " spent of " + formatMoney(b.funded, b.currency) + " funded"
    if (b.estimated) text += " · estimated"
    return text
  }

  // ---------------------------------------------------------------- content

  // The plan you pay for, under the name of the tool it pays for. Limits live
  // in their own section; the hero just says what this is.
  function heroMeta(p) {
    if (!p) return ""
    if (String(p.usageStatusText || "") !== "") return p.usageStatusText
    var tier = String(p.tierLabel || "")
    if (tier === "") return "Subscription"
    return tier.charAt(0).toUpperCase() + tier.slice(1)
  }

  // Local calendar date, recomputed from nowMs so a panel left open across
  // midnight moves the "Today" row with the clock.
  function todayDate() {
    var now = new Date(root.nowMs)
    return now.getFullYear()
      + "-" + String(now.getMonth() + 1).padStart(2, "0")
      + "-" + String(now.getDate()).padStart(2, "0")
  }

  function dayName(date) {
    var parsed = new Date(String(date || "") + "T00:00:00")
    if (isNaN(parsed.getTime())) return String(date || "")
    return ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][parsed.getDay()]
  }

  function dayLabel(date, today) {
    if (today) return "Today"
    return dayName(date)
  }

  function dayTooltip(day, today) {
    if (!day) return ""
    var parsed = new Date(String(day.date) + "T00:00:00")
    var label = isNaN(parsed.getTime())
      ? String(day.date)
      : dayName(day.date) + " " + (parsed.getMonth() + 1) + "/" + parsed.getDate()
    var text = label + " · " + usage.formatTokenCount(Number(day.messageCount || 0)) + " tokens"
    // Prompt and session counts only exist for today, so they ride along here
    // instead of taking a section of their own. Billing-API agents never
    // count prompts, and "0 prompts" would read as a quiet day, not a gap.
    if (today && provider && provider.hasPromptStats !== false)
      text += " · " + Number(provider.todayPrompts || 0) + " prompts · "
        + Number(provider.todaySessions || 0) + " sessions"
    return text
  }

  function weekPeak(p) {
    var days = p ? (p.recentDays || []) : []
    var peak = 0
    for (var i = 0; i < days.length; i++) peak = Math.max(peak, Number(days[i].messageCount || 0))
    return peak
  }

  function modelRows(p) {
    var usageByModel = p ? (p.modelUsage || {}) : {}
    var rows = []
    for (var id in usageByModel) {
      var bucket = usageByModel[id] || {}
      var input = Number(bucket.inputTokens || 0)
      var output = Number(bucket.outputTokens || 0)
      var cacheRead = Number(bucket.cacheReadInputTokens || 0)
      var cacheWrite = Number(bucket.cacheCreationInputTokens || 0)
      rows.push({
        name: usage.friendlyModelName(id),
        total: input + output + cacheRead + cacheWrite,
        input: input,
        output: output,
        cacheRead: cacheRead,
        cacheWrite: cacheWrite
      })
    }
    rows.sort(function(a, b) { return b.total - a.total })
    return rows.slice(0, 4)
  }

  function modelTooltip(row) {
    if (!row) return ""
    return "In " + usage.formatTokenCount(row.input)
      + " · out " + usage.formatTokenCount(row.output)
      + " · cache read " + usage.formatTokenCount(row.cacheRead)
      + " · cache write " + usage.formatTokenCount(row.cacheWrite)
  }

  // Only speaks up when the numbers cover more than this machine.
  function footerText() {
    if (usage.syncStatusText !== "") return usage.syncStatusText
    if (provider && provider.syncEnabled && provider.syncDeviceCount > 0)
      return "Merged from " + provider.syncDeviceCount + " device" + (provider.syncDeviceCount === 1 ? "" : "s")
    return ""
  }

  // Agents that ship a white mark carry an `assets/<id>-light.svg` twin for
  // light surfaces; marks that work on both (Claude's brand-orange) ship one
  // file. The luminance check decides which candidate to try first.
  function colorChannelLuminance(value) {
    var channel = Number(value)
    if (!isFinite(channel)) return 0
    return channel <= 0.03928 ? channel / 12.92 : Math.pow((channel + 0.055) / 1.055, 2.4)
  }

  function colorLuminance(color) {
    return 0.2126 * colorChannelLuminance(color.r)
      + 0.7152 * colorChannelLuminance(color.g)
      + 0.0722 * colorChannelLuminance(color.b)
  }

  // Marks resolve by convention, so a new agent's data file needs nothing
  // from this panel: assets/<id>.svg if it ships one, the module's bar glyph
  // if it doesn't.
  function iconCandidatesForProvider(p, surfaceColor) {
    if (!p) return []
    if (/^grok(?:-|$)/.test(p.providerId)) return []
    var candidates = []
    if (colorLuminance(surfaceColor || Color.background) >= 0.5)
      candidates.push(Qt.resolvedUrl("assets/" + p.providerId + "-light.svg"))
    candidates.push(Qt.resolvedUrl("assets/" + p.providerId + ".svg"))
    return candidates
  }

  // Keep account setup reachable even before the first login has usage.
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  onProviderIndexChanged: if (!overview && panelFlick) panelFlick.contentY = 0
  onOpenedChanged: if (opened) {
    overview = true
    cursorActive = false
    nowMs = Date.now()
    refreshResetLabels()
    if (panelFlick) panelFlick.contentY = 0
    usage.refreshLimits()
    Qt.callLater(function() { keyCatcher.forceActiveFocus() })
  } else {
    accountSelector.close()
    addAccountDialog.close()
    editAccountDialog.close()
    overviewSettingsDialog.close()
  }

  Main {
    id: usage
    settings: root.persistedSettings
  }

  Process {
    id: reauthLauncher
    property string requestKey: ""
    stderr: StdioCollector {
      onStreamFinished: if (reauthLauncher.requestKey === root.identityKey && text.trim())
        root.reauthError = text.trim()
    }
    onExited: function(code) {
      if (code === 0) root.close()
      else if (requestKey === root.identityKey && !root.reauthError)
        root.reauthError = "Unable to open the terminal. Please try again."
    }
  }

  Process {
    id: identityProcess
    property string requestKey: ""
    stdout: StdioCollector {
      onStreamFinished: {
        var result
        try { result = JSON.parse(text) }
        catch (e) { result = { email: "", status: "Email unavailable" } }
        root.accountIdentity = { key: identityProcess.requestKey,
          email: String(result.email || ""), status: String(result.status || "") }
      }
    }
    onExited: {
      if (root.identityRefreshPending) {
        root.identityRefreshPending = false
        Qt.callLater(root.refreshIdentity)
      }
    }
  }

  Process {
    id: resetLabelProcess
    stdout: StdioCollector {
      onStreamFinished: {
        try { root.resetLabels = JSON.parse(text) }
        catch (e) { console.warn("agents: unable to format local reset times") }
      }
    }
    onExited: {
      if (root.resetRefreshPending) {
        root.resetRefreshPending = false
        Qt.callLater(root.refreshResetLabels)
      }
    }
  }

  // Use a fresh local-zone conversion so OS time-zone changes take effect too.
  Timer {
    interval: 30000
    running: root.opened
    repeat: true
    onTriggered: {
      root.nowMs = Date.now()
      root.refreshResetLabels()
      root.refreshIdentity()
    }
  }

  IpcHandler {
    target: root.ipcTarget
    function open(): void { root.open() }
    function close(): void { root.close() }
    function show(): void { root.open() }
    function hide(): void { root.close() }
    function toggle(): void { root.toggle() }
    function refresh(): string { root.refreshNow(); return "ok" }
    function next(): string { root.selectCompany(root.companyIndex + 1); return "ok" }
  }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: "󱚣"
    active: root.alarming
    onPressed: function(buttonCode) {
      if (buttonCode === Qt.RightButton) root.launchAgent()
      else if (buttonCode === Qt.MiddleButton) root.selectCompany(root.companyIndex + 1)
      else root.toggle()
    }
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(380))
    // Taller than the control panels on purpose: this one is a dashboard, and
    // the whole point is reading limits and history without scrolling.
    contentHeight: panel.fittedContentHeight(Math.max(column.implicitHeight + providerTabs.height + Style.space(12),
      addAccountDialog.opened ? addAccountDialog.minimumHeight : 0,
      editAccountDialog.opened ? editAccountDialog.minimumHeight : 0,
      overviewSettingsDialog.opened ? overviewSettingsDialog.minimumHeight : 0), Style.space(640))

    AddAccountDialog {
      id: addAccountDialog
      anchors.fill: parent
      z: 10
      foreground: root.foreground
      fontFamily: root.fontFamily
      onCanceled: { close(); keyCatcher.forceActiveFocus() }
      onLaunched: { close(); root.close() }
    }

    EditAccountDialog {
      id: editAccountDialog
      anchors.fill: parent
      z: 10
      foreground: root.foreground
      fontFamily: root.fontFamily
      onCanceled: { close(); keyCatcher.forceActiveFocus() }
      onSaveRequested: function(accountId, name) {
        errorText = root.renameAccount(accountId, name)
        if (!errorText) { close(); keyCatcher.forceActiveFocus() }
      }
    }

    OverviewSettingsDialog {
      id: overviewSettingsDialog
      anchors.fill: parent
      z: 10
      foreground: root.foreground
      fontFamily: root.fontFamily
      sortOptions: root.sortOptions
      onCanceled: { close(); keyCatcher.forceActiveFocus() }
      onSaveRequested: function(companyId, metric, sort) {
        errorText = root.saveOverviewSettings(companyId, metric, sort)
        if (!errorText) { close(); keyCatcher.forceActiveFocus() }
      }
    }

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      blocked: accountSelector.popupOpen || addAccountDialog.opened || editAccountDialog.opened || overviewSettingsDialog.opened
      enabled: !addAccountDialog.opened && !editAccountDialog.opened && !overviewSettingsDialog.opened

      onMoveRequested: function(dx, dy) {
        if (dx !== 0) {
          root.selectCompany(root.companyIndex + dx)
          return
        }
        if (root.overview) {
          if (dy !== 0) root.moveOverviewCursor(dy)
          return
        }
        if (dy !== 0)
          panelFlick.contentY = root.clamp(panelFlick.contentY + dy * Style.space(56), 0,
                                           Math.max(0, panelFlick.contentHeight - panelFlick.height))
      }
      onActivateRequested: {
        if (root.overview) root.showDetails(root.providerIndex)
        else if (accountSelector.visible) accountSelector.open()
        else root.refreshNow()
      }
      onCloseRequested: {
        if (root.overview) root.close()
        else root.showOverview()
      }
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onTextKey: function(t) {
        if (t === "r" || t === "R") root.refreshNow()
        else if ((t === "s" || t === "S") && root.overview && root.providers.length > 0) root.openOverviewSettings()
        else if (t === "+") addAccountDialog.open(root.companyId)
      }

      Row {
        id: providerTabs
        anchors.top: parent.top
        width: parent.width
        spacing: Style.space(8)

        Item {
          visible: root.companies.length === 0
          width: providerTabs.width - addAccountButton.width - providerTabs.spacing
          height: 1
        }

        Repeater {
          model: root.companies
          Button {
            required property var modelData
            required property int index
            width: (providerTabs.width - addAccountButton.width - providerTabs.spacing * root.companies.length) / Math.max(1, root.companies.length)
            text: modelData.label
            selected: modelData.value === root.companyId
            bordered: true
            foreground: root.foreground
            fontFamily: root.fontFamily
            fontSize: Style.font.bodySmall
            onClicked: root.selectCompany(index)
          }
        }
        Button {
          id: addAccountButton
          width: implicitHeight
          text: "+"
          tooltipText: "Add account"
          bordered: true
          foreground: root.foreground
          fontFamily: root.fontFamily
          fontSize: Style.font.bodySmall
          onClicked: {
            accountSelector.close()
            addAccountDialog.open(root.companyId)
          }
        }
      }

      Flickable {
        id: panelFlick
        anchors.top: providerTabs.bottom
        anchors.topMargin: Style.space(12)
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        contentWidth: width
        contentHeight: column.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        flickableDirection: Flickable.VerticalFlick
        interactive: contentHeight > height
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        Column {
          id: column
          width: panelFlick.width
          spacing: Style.space(12)

          Column {
            visible: root.overview
            width: parent.width
            spacing: Style.space(12)

            Text {
              text: root.overviewHeading
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.title
              font.bold: true
            }
            Row {
              width: parent.width
              spacing: Style.space(6)
              Text {
                text: root.providers.length > 0
                  ? root.providers.length + (root.providers.length === 1 ? " account" : " accounts")
                    + (overviewSettingsLink.visible ? " ·" : "")
                  : "Add an account with + to get started."
                color: root.dim
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
              }
              AccountLink {
                id: overviewSettingsLink
                objectName: "overviewSettingsLink"
                text: "settings"
                visible: root.providers.length > 0
                onClicked: root.openOverviewSettings()
              }
            }

            Repeater {
              id: overviewRows
              model: root.providers
              OverviewAccountRow {
                required property var modelData
                required property int index
                width: parent.width
                account: modelData
                hasCursor: root.cursorActive && index === root.providerIndex
                onChosen: root.showDetails(index)
              }
            }

            Text {
              width: parent.width
              text: "←/→ switch providers · Enter opens account details."
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              wrapMode: Text.WordWrap
            }
          }

          Column {
            visible: !root.overview
            width: parent.width
            spacing: Style.space(12)

            Button {
              text: "← " + root.companyName + " accounts"
              foreground: root.foreground
              fontFamily: root.fontFamily
              onClicked: root.showOverview()
            }
            // ---------- Hero: provider mark · name · plan and email ----------
            Item {
              id: hero
              visible: !!root.provider
              width: parent.width
              implicitHeight: Math.max(heroIcon.implicitHeight, heroLabels.implicitHeight)

              Loader {
                id: heroIcon
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                sourceComponent: Component {
                  Item {
                    id: heroMark
                    property var candidates: root.iconCandidatesForProvider(root.provider, root.surface)
                    // Provider objects are rebuilt on every refresh, which churns the
                    // array's identity without changing its content. Restart the fallback
                    // walk only when the URLs change: re-pointing source at a URL whose
                    // load already failed emits no statusChanged, so an identity-only
                    // reset would strand the walker on a missing -light twin.
                    property string candidatesKey: candidates.join("\n")
                    property int candidateIndex: 0
                    onCandidatesKeyChanged: candidateIndex = 0

                    width: Style.font.display
                    height: Style.font.display

                    Image {
                      id: heroMarkImage
                      anchors.fill: parent
                      source: heroMark.candidateIndex < heroMark.candidates.length ? heroMark.candidates[heroMark.candidateIndex] : ""
                      sourceSize.width: Style.font.display * 2
                      sourceSize.height: Style.font.display * 2
                      fillMode: Image.PreserveAspectFit
                      // Advancing source from inside its own status change trips the
                      // binding-loop detector; defer the step one tick.
                      onStatusChanged: if (status === Image.Error && heroMark.candidateIndex < heroMark.candidates.length)
                        Qt.callLater(function() { heroMark.candidateIndex++ })
                    }

                    Text {
                      textFormat: Text.PlainText
                      anchors.centerIn: parent
                      visible: heroMarkImage.status !== Image.Ready
                      text: button.text
                      color: root.foreground
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.display
                    }
                  }
                }
              }

              Column {
                id: heroLabels
                anchors.left: heroIcon.right
                anchors.leftMargin: Style.space(14)
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                spacing: Style.space(2)

                Text {
                  width: parent.width
                  text: root.provider ? root.provider.providerName : ""
                  textFormat: Text.PlainText
                  color: root.foreground
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.title
                  font.bold: true
                  elide: Text.ElideRight
                }

                Row {
                  width: parent.width
                  spacing: Style.space(10)

                  Text {
                    id: planLabel
                    width: Math.min(implicitWidth, parent.width * 0.45)
                    text: root.heroMeta(root.provider).toUpperCase()
                    textFormat: Text.PlainText
                    color: root.dim
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                    font.bold: true
                    font.letterSpacing: 1.2
                    elide: Text.ElideRight
                  }

                  Text {
                    objectName: "accountEmail"
                    width: Math.min(implicitWidth, Math.max(0, parent.width - planLabel.width - parent.spacing
                      - (reauthLink.visible ? reauthLink.width + parent.spacing : 0)
                      - editLink.width - parent.spacing))
                    text: root.identityText
                    textFormat: Text.PlainText
                    color: root.foreground
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                    elide: Text.ElideRight
                    ToolTip.visible: emailHover.hovered && truncated
                    ToolTip.text: text
                    HoverHandler { id: emailHover }
                  }

                  AccountLink {
                    id: reauthLink
                    objectName: "reauthenticateAccount"
                    visible: root.canReauthenticate
                    enabled: !reauthLauncher.running
                    text: "re-auth"
                    Accessible.name: "Re-authenticate account"
                    onClicked: root.reauthenticate()
                  }

                  AccountLink {
                    id: editLink
                    objectName: "editAccount"
                    text: "edit"
                    Accessible.name: "Edit account name"
                    onClicked: {
                      accountSelector.close()
                      editAccountDialog.open(root.provider)
                    }
                  }
                }
              }
            }

            Text {
              visible: text !== ""
              width: parent.width
              text: root.reauthError
              textFormat: Text.PlainText
              color: root.urgent
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              wrapMode: Text.WordWrap
            }

            Text {
              visible: root.providers.length === 0
              width: parent.width
              topPadding: Style.space(24)
              text: "No AI coding subscriptions found.\nAgents show up here once you've used them."
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.body
              horizontalAlignment: Text.AlignHCenter
              wrapMode: Text.WordWrap
            }

            // One full-width selector keeps account names readable as the list grows.
            Dropdown {
              id: accountSelector
              visible: root.providers.length > 1
              width: parent.width
              label: "Account"
              foreground: root.foreground
              fontFamily: root.fontFamily
              hasCursor: root.cursorActive
              options: root.providers.map(function(p) {
                return { value: p.providerId, label: p.providerName }
              })

              // Dropdown assigns value on selection; keep this binding explicit so
              // cycling with Left/Right or IPC also updates the displayed account.
              Binding {
                target: accountSelector
                property: "value"
                value: root.provider ? root.provider.providerId : ""
              }
              onChanged: function(value) {
                for (var i = 0; i < root.providers.length; i++) {
                  if (root.providers[i].providerId === value) {
                    root.selectProvider(i)
                    break
                  }
                }
                root.cursorActive = true
              }
              onPopupOpenChanged: if (!popupOpen && root.opened)
                keyCatcher.forceActiveFocus()
              onHovered: function(isHovered) { if (isHovered) root.cursorActive = true }
            }

            Text {
              width: parent.width
              visible: text !== ""
              text: root.provider ? root.provider.usageNote : ""
              textFormat: Text.PlainText
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              wrapMode: Text.WordWrap
            }

            // ---------- Status ----------
            BorderSurface {
              visible: !!root.provider && String(root.provider.usageStatusText || "") !== ""
              width: parent.width
              implicitHeight: statusText.implicitHeight + Style.spacing.xl * 2
              color: root.alpha(root.urgent, 0.10)
              borderSpec: Border.flat(root.alpha(root.urgent, 0.35), 1)
              radius: Style.cornerRadius

              Text {
                id: statusText
                textFormat: Text.PlainText
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: Style.space(12)
                anchors.rightMargin: Style.space(12)
                text: root.provider ? String(root.provider.authHelpText || "") : ""
                color: root.dim
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
                wrapMode: Text.WordWrap
              }
            }

            // ---------- Balance / limits ----------
            PanelSeparator {
              visible: balanceSection.visible || limitsSection.visible
              foreground: root.foreground
            }

            Column {
              id: balanceSection
              visible: !!root.balance
              width: parent.width
              spacing: Style.space(10)

              // The meter shows what is left, not what is used: a prepaid
              // account drains toward empty rather than filling toward a cap.
              readonly property real ratio: root.balance && root.balance.funded > 0
                ? root.clamp(root.balance.remaining / root.balance.funded, 0, 1)
                : -1

              PanelSectionHeader {
                width: parent.width
                text: "BALANCE"
                foreground: root.foreground
                fontFamily: root.fontFamily
              }

              Item {
                width: parent.width
                implicitHeight: Math.max(balanceLabel.implicitHeight, balanceValue.implicitHeight)

                Text {
                  id: balanceLabel
                  text: "Prepaid credits"
                  color: root.foreground
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.body
                  anchors.left: parent.left
                  anchors.verticalCenter: parent.verticalCenter
                }

                Text {
                  id: balanceValue
                  textFormat: Text.PlainText
                  text: root.balance ? root.formatMoney(root.balance.remaining, root.balance.currency) : ""
                  color: root.balanceAlarming ? root.urgent : root.foreground
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                  anchors.right: parent.right
                  anchors.verticalCenter: parent.verticalCenter
                }
              }

              Meter {
                visible: balanceSection.ratio >= 0
                width: parent.width
                value: balanceSection.ratio
                alarming: root.balanceAlarming
              }

              Text {
                textFormat: Text.PlainText
                visible: text !== ""
                width: parent.width
                text: root.balanceDetailText(root.balance)
                color: root.dim
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
              }
            }

            Column {
              id: limitsSection
              visible: root.limits.length > 0
              width: parent.width
              spacing: Style.space(10)

              PanelSectionHeader {
                text: "LIMITS"
                foreground: root.foreground
                fontFamily: root.fontFamily
              }

              Repeater {
                model: root.limits

                LimitRow {
                  required property var modelData
                  width: limitsSection.width
                  window: modelData
                }
              }
            }

            // ---------- Usage ----------
            PanelSeparator {
              visible: usageSection.visible
              foreground: root.foreground
            }

            Column {
              id: usageSection
              visible: !!root.provider && root.provider.recentDays && root.provider.recentDays.length > 0
              width: parent.width
              spacing: Style.spacing.md

              readonly property var days: root.provider ? (root.provider.recentDays || []) : []
              readonly property real peak: Math.max(1, root.weekPeak(root.provider))

              PanelSectionHeader {
                width: parent.width
                text: "TOKENS BY DAY"
                foreground: root.foreground
                fontFamily: root.fontFamily
              }

              Repeater {
                model: usageSection.days

                DayRow {
                  required property var modelData
                  required property int index

                  width: usageSection.width
                  day: modelData
                  ratio: Number(modelData.messageCount || 0) / usageSection.peak
                  // By date, not by position: the Claude stats-cache fallback can
                  // hand us a window that stops short of today.
                  today: String(modelData.date || "") === root.todayDate()
                }
              }
            }

            // ---------- Models ----------
            PanelSeparator {
              visible: modelSection.visible
              foreground: root.foreground
            }

            Column {
              id: modelSection
              visible: root.models.length > 0
              width: parent.width
              spacing: Style.spacing.md

              PanelSectionHeader {
                width: parent.width
                text: "TOKENS BY MODEL"
                foreground: root.foreground
                fontFamily: root.fontFamily
              }

              Repeater {
                model: root.models

                ModelRow {
                  required property var modelData
                  width: modelSection.width
                  row: modelData
                  // Scaled to the heaviest model, so the top row is always full —
                  // the same scale-to-peak the weekly chart uses for its busiest day.
                  share: modelData.total / Math.max(1, root.models[0].total)
                }
              }
            }

            Text {
              textFormat: Text.PlainText
              visible: text !== ""
              width: parent.width
              topPadding: Style.space(2)
              text: root.footerText()
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              horizontalAlignment: Text.AlignHCenter
              elide: Text.ElideRight
            }
          }
        }
      }
    }
  }

  component OverviewAccountRow: BorderSurface {
    id: accountRow
    property var account: null
    property bool hasCursor: false
    signal chosen()
    readonly property var window: root.overviewWindow(account)
    readonly property bool warning: window && window.percent >= 0.9
    readonly property bool hot: rowMouse.containsMouse || hasCursor
    implicitHeight: rowContent.implicitHeight + Style.space(20)
    radius: Style.cornerRadius
    color: hot ? Style.hoverFillFor(root.foreground, Color.accent) : "transparent"
    borderSpec: Border.controlSpec(hot ? "hover-cursor" : "normal", root.foreground, Color.accent)

    Column {
      id: rowContent
      x: Style.space(10)
      y: Style.space(10)
      width: parent.width - Style.space(20)
      spacing: Style.space(7)

      Item {
        width: parent.width
        implicitHeight: Math.max(accountName.implicitHeight, overviewValue.implicitHeight)
        Text {
          id: accountName
          textFormat: Text.PlainText
          anchors.left: parent.left
          anchors.right: overviewValue.left
          anchors.rightMargin: Style.space(12)
          text: accountRow.account ? accountRow.account.providerName : ""
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.body
          elide: Text.ElideRight
        }
        Text {
          id: overviewValue
          anchors.right: parent.right
          text: accountRow.window ? Math.round(accountRow.window.percent * 100) + "% used  ›" : "—  ›"
          color: accountRow.warning ? root.urgent : root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          font.bold: true
        }
      }

      Meter {
        width: parent.width
        visible: !!accountRow.window
        value: accountRow.window ? accountRow.window.percent : 0
        alarming: accountRow.warning
      }
      Text {
        width: parent.width
        text: root.overviewResetText(accountRow.account, accountRow.window)
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        wrapMode: Text.WordWrap
      }
      Text {
        textFormat: Text.PlainText
        width: parent.width
        visible: text !== ""
        text: accountRow.account ? String(accountRow.account.usageStatusText || "") : ""
        color: root.urgent
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        wrapMode: Text.WordWrap
      }
    }
    MouseArea {
      id: rowMouse
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onClicked: accountRow.chosen()
    }
  }

  // A limit window: label and percentage, meter, and local reset day/time.
  component LimitRow: Column {
    id: limitRow
    property var window: null

    readonly property bool alarming: window && window.percent >= 0.9

    spacing: Style.space(6)

    Item {
      width: parent.width
      implicitHeight: Math.max(limitLabel.implicitHeight, limitValue.implicitHeight)

      Text {
        id: limitLabel
        textFormat: Text.PlainText
        // A model-scoped window is titled after its model, and those names run
        // long enough to reach the percentage, so the title gives way first.
        text: limitRow.window ? limitRow.window.title : ""
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
        elide: Text.ElideRight
        anchors.left: parent.left
        anchors.right: limitValue.left
        anchors.rightMargin: Style.spacing.sm
        anchors.verticalCenter: parent.verticalCenter
      }

      Text {
        id: limitValue
        textFormat: Text.PlainText
        text: limitRow.window && limitRow.window.percent >= 0
          ? Math.round(limitRow.window.percent * 100) + "%"
          : "—"
        color: limitRow.alarming ? root.urgent : root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
      }
    }

    Meter {
      width: parent.width
      value: limitRow.window ? limitRow.window.percent : -1
      alarming: limitRow.alarming
    }

    Text {
      id: resetText
      textFormat: Text.PlainText
      width: parent.width
      text: root.resetLabel(limitRow.window)
      color: root.dim
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
      wrapMode: Text.WordWrap
    }
  }

  // Rounded track showing the percentage of the allowance used.
  component Meter: Item {
    id: meter
    property real value: -1
    property bool alarming: false
    property real thickness: Math.max(Style.space(4), Math.round(Style.spacing.controlHeight * 0.14))

    implicitHeight: thickness

    Rectangle {
      id: meterTrack
      anchors.fill: parent
      radius: height / 2
      color: root.track
    }

    Rectangle {
      anchors.left: meterTrack.left
      anchors.verticalCenter: meterTrack.verticalCenter
      height: meterTrack.height
      radius: meterTrack.radius
      width: meterTrack.width * root.clamp(meter.value, 0, 1)
      color: meter.alarming ? root.urgent : root.foreground

      Behavior on width {
        NumberAnimation { duration: 160; easing.type: Easing.OutCubic }
      }
    }

  }

  // One row per day: label, bar, tokens. Today is picked out in full
  // foreground so the week reads as a run-up to right now.
  component DayRow: Item {
    id: dayRow
    property var day: null
    property real ratio: 0
    property bool today: false

    implicitHeight: Math.max(dayLabel.implicitHeight, dayValue.implicitHeight) + Style.spacing.sm

    Text {
      id: dayLabel
      textFormat: Text.PlainText
      text: root.dayLabel(dayRow.day ? dayRow.day.date : "", dayRow.today)
      color: dayRow.today ? root.foreground : root.dim
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
      font.bold: dayRow.today
      anchors.left: parent.left
      anchors.verticalCenter: parent.verticalCenter
      width: Style.space(52)
    }

    Rectangle {
      id: dayTrack
      anchors.left: dayLabel.right
      anchors.right: dayValue.left
      anchors.leftMargin: Style.space(8)
      anchors.rightMargin: Style.space(10)
      anchors.verticalCenter: parent.verticalCenter
      height: Math.max(Style.space(4), Math.round(Style.spacing.controlHeight * 0.14))
      radius: height / 2
      color: root.track

      Rectangle {
        anchors.left: parent.left
        anchors.verticalCenter: parent.verticalCenter
        height: parent.height
        radius: parent.radius
        width: parent.width * root.clamp(dayRow.ratio, 0, 1)
        color: dayRow.today ? root.foreground : root.alpha(root.foreground, 0.55)

        Behavior on width {
          NumberAnimation { duration: 160; easing.type: Easing.OutCubic }
        }
      }
    }

    Text {
      id: dayValue
      textFormat: Text.PlainText
      text: usage.formatTokenCount(dayRow.day ? Number(dayRow.day.messageCount || 0) : 0)
      color: dayRow.today ? root.foreground : root.dim
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
      font.bold: true
      horizontalAlignment: Text.AlignRight
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      width: Style.space(52)
    }

    MouseArea {
      id: dayHover
      anchors.fill: parent
      hoverEnabled: true
      acceptedButtons: Qt.NoButton
    }

    PanelToolTip {
      visible: dayHover.containsMouse
      text: root.dayTooltip(dayRow.day, dayRow.today)
      fontFamily: root.fontFamily
    }
  }

  // Model rows read as a table: the share bar fills the row behind the label
  // instead of stacking under it, which keeps the whole dashboard on one screen.
  component ModelRow: Item {
    id: modelRow
    property var row: null
    property real share: 0

    implicitHeight: modelName.implicitHeight + Style.spacing.lg

    Rectangle {
      anchors.fill: parent
      radius: Style.cornerRadius
      color: root.alpha(root.foreground, 0.05)
    }

    Rectangle {
      anchors.left: parent.left
      anchors.top: parent.top
      anchors.bottom: parent.bottom
      width: parent.width * root.clamp(modelRow.share, 0, 1)
      radius: Style.cornerRadius
      color: root.alpha(root.foreground, 0.14)

      Behavior on width {
        NumberAnimation { duration: 160; easing.type: Easing.OutCubic }
      }
    }

    Text {
      id: modelName
      textFormat: Text.PlainText
      text: modelRow.row ? modelRow.row.name : ""
      color: root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.bodySmall
      elide: Text.ElideRight
      anchors.left: parent.left
      anchors.leftMargin: Style.space(8)
      anchors.right: modelTokens.left
      anchors.rightMargin: Style.space(8)
      anchors.verticalCenter: parent.verticalCenter
    }

    Text {
      id: modelTokens
      textFormat: Text.PlainText
      text: modelRow.row ? usage.formatTokenCount(modelRow.row.total) : ""
      color: root.dim
      font.family: root.fontFamily
      font.pixelSize: Style.font.bodySmall
      font.bold: true
      anchors.right: parent.right
      anchors.rightMargin: Style.space(8)
      anchors.verticalCenter: parent.verticalCenter
    }

    MouseArea {
      id: modelHover
      anchors.fill: parent
      hoverEnabled: true
      acceptedButtons: Qt.NoButton
    }

    PanelToolTip {
      visible: modelHover.containsMouse
      text: root.modelTooltip(modelRow.row)
      fontFamily: root.fontFamily
    }
  }
}
