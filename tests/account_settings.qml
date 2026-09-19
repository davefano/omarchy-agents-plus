import QtQuick
import Quickshell
import Quickshell.Io
import "." as Plugin
import qs.Commons
ShellRoot {
  id: test
  property var saved: null
  property int writes: 0
  property bool failWrite: false
  property var original: ({ refreshIntervalSec: 123, providers: {
    claude: {enabled:true, custom:"keep"}, codex: {enabled:true, name:"Existing"},
    "codex-disabled": {enabled:false, name:"Disabled"} } })
  QtObject {
    id: fakeBar
    property color foreground: "white"
    property color barForeground: "white"
    property bool vertical: false
    property int barSize: 32
    property bool foregroundAnimationEnabled: false
    property string position: "top"
    property color urgent: "red"
    property string fontFamily: "monospace"
    property QtObject shell: QtObject {
      id: shell
      property var shellConfig: ({version:1, bar:{layout:{right:[Object.assign({id:"davidfano.agents"}, test.original)]}}})
      property var builtinShellConfig: ({})
      function persistShellConfig(next) {
        shellConfig = next
        test.saved = JSON.parse(JSON.stringify(next.bar.layout.right[0]))
        test.writes++
        configFile.setText(JSON.stringify(next))
      }
      // Supplied by the test runner from the installed Omarchy shell.
      // UPDATE_ENTRY_INLINE

    }
  }
  FileView {
    id: configFile
    path: Quickshell.shellDir + "/saved-shell.json"
    atomicWrites: true
    printErrors: false
  }
  Plugin.Panel { id: panel; moduleName: "davidfano.agents"; bar: fakeBar; settings: test.original }
  Plugin.Main { id: reloaded; settings: test.saved || ({}) }
  Plugin.EditAccountDialog {
    id: dialog; width:380; height:400
    onCanceled: close()
    onSaveRequested: function(id, name) {
      errorText = panel.renameAccount(id,name)
      if (!errorText) close()
    }
  }
  Plugin.OverviewSettingsDialog {
    id: overviewDialog; width:380; height:500; sortOptions: panel.sortOptions
    onCanceled: close()
    onSaveRequested: function(company, metric, sort) {
      errorText = panel.saveOverviewSettings(company, metric, sort)
      if (!errorText) close()
    }
  }
  function find(item,name) {
    if (item.objectName === name) return item
    var children = item.children || []
    for (var i=0;i<children.length;i++) { var result=find(children[i],name); if(result) return result }
    return null
  }
  function check(ok,message) { if(!ok) { console.error("FAILED: "+message); Qt.quit(); throw new Error(message) } }
  Timer {
    id: finish
    interval: 300
    onTriggered: { console.log("ACCOUNT_SETTINGS_REGRESSION_PASSED"); Qt.quit() }
  }
  Timer {
    interval:400; running:true; repeat:true
    property int attempts:0
    onTriggered: {
      if (++attempts > 15) { check(false,"Timeout"); return }
      if(panel.companies.length !== 3 || reloaded.enabledProviders.length !== 4) return
      panel.selectCompany(0)
      panel.showDetails(0)
      dialog.open(panel.provider)
      var field = find(dialog,"editAccountName")
      check(field && field.text === "Claude", "Editor is not prefilled")
      field.text = "Canceled name"
      dialog.canceled()
      check(writes === 0 && panel.provider.providerName === "Claude", "Cancel changed name")
      dialog.open(panel.provider)
      field.text = "   "
      dialog.submit()
      check(dialog.opened && writes === 0, "Blank name saved")
      field.text = "  Personal <&>  "
      dialog.submit()
      check(!dialog.opened && panel.provider.providerName === "Personal <&>", "Name did not update")
      check(saved.providers.claude.custom === "keep" && saved.providers.claude.enabled, "Account options lost")
      check(saved.refreshIntervalSec === 123 && !saved.providers["codex-disabled"].enabled, "Other settings lost")
      check(original.providers.claude.name === undefined, "Original settings mutated")
      check(reloaded.enabledProviders[0].providerName === "Personal <&>", "Stored override not used after reload")
      // Bar ModuleSlot.injectProps uses its original entry again after a reload.
      panel.settings = test.original
      check(panel.provider.providerName === "Personal <&>", "Reload hides the saved account name")
      panel.selectCompany(1)
      panel.showDetails(0)
      check(panel.provider.providerName === "Existing", "Other account renamed")
      dialog.open(panel.provider)
      panel.selectCompany(0)
      field.text = "Work"
      dialog.submit()
      check(saved.providers.codex.name === "Work" && saved.providers.claude.name === "Personal <&>", "Later edit overwrites an earlier saved account name")
      dialog.open(panel.provider)
      test.failWrite = true
      field.text = "Cannot save"
      dialog.submit()
      check(dialog.opened && dialog.errorText !== "" && panel.provider.providerName === "Personal <&>", "Persistence failure hidden")
      dialog.close()
      test.failWrite = false
      panel.showOverview()
      check(panel.overviewMetric("anthropic") === "weekly", "New installs should default to overall weekly")
      check(panel.overviewOptions.length === 3, "Anthropic options should come from reported limits")
      check(panel.metricOptions("openai").length === 1 && panel.metricOptions("xai").length === 1,
            "Single-limit companies should offer one metric")
      check(panel.overviewWindow(panel.provider).percent === 0.3, "Default meter should use overall weekly")
      overviewDialog.open("anthropic", "Anthropic", panel.overviewOptions, panel.overviewMetric("anthropic"))
      var selector = find(overviewDialog, "overviewMetric")
      check(selector.value === "weekly", "Settings should be prefilled")
      var oldWrites = writes
      selector.value = "session (5-hour)"
      overviewDialog.canceled()
      check(writes === oldWrites && panel.overviewMetric("anthropic") === "weekly", "Cancel changed the meter")
      overviewDialog.open("anthropic", "Anthropic", panel.overviewOptions, "weekly")
      selector.value = "session (5-hour)"
      overviewDialog.submit()
      check(!overviewDialog.opened && panel.overviewWindow(panel.provider).percent === 0.1,
            "Save did not update session meter")
      check(panel.overviewHeading === "Session limits", "Session heading should not say weekly")
      check(panel.limitWindows(panel.provider).length === 3, "Overview selection hid detail limits")
      panel.settings = test.original
      check(panel.overviewMetric("anthropic") === "session (5-hour)", "Stale reinjection lost selected metric")
      check(panel.saveOverviewSettings("anthropic", "fable weekly") === "", "Could not select Fable")
      check(panel.overviewWindow(panel.provider).percent === 0.8, "Fable meter did not update")
      var noFable = {providerId:"claude-extra", limits:[{label:"weekly",percent:0.4}]}
      check(panel.overviewWindow(noFable) === null, "Missing Fable fell back to an unrelated meter")
      check(panel.overviewResetText(noFable, null) === "Fable weekly usage unavailable", "Unavailable metric is unlabeled")
      check(panel.renameAccount("claude", "Updated personal") === "", "Rename failed after metric save")
      check(saved.overviewMetrics.anthropic === "fable weekly" && saved.providers.codex.name === "Work",
            "Saving one setting erased another")
      panel.selectCompany(1)
      check(panel.overviewMetric("openai") === "weekly" && panel.overviewWindow(panel.provider).percent === 0.3,
            "Anthropic settings affected OpenAI")
      panel.showDetails(0)
      check(panel.limitWindows(panel.provider).length === 1, "OpenAI details changed")
      panel.selectCompany(2)
      panel.showDetails(0)
      check(panel.overviewMetric("xai") === "weekly" && panel.limitWindows(panel.provider).length === 1,
            "Grok details changed")
      overviewDialog.open("anthropic", "Anthropic", panel.metricOptions("anthropic"), "fable weekly")
      test.failWrite = true
      selector.value = "weekly"
      overviewDialog.submit()
      check(overviewDialog.opened && overviewDialog.errorText !== "" && saved.overviewMetrics.anthropic === "fable weekly",
            "Overview save failure hidden")
      test.failWrite = false
      check(panel.saveOverviewSettings("anthropic", "unknown") !== "", "Invalid metric accepted")
      check(panel.saveOverviewSettings("anthropic", "weekly", "unknown") !== "", "Invalid sort accepted")

      // Sort the selected metric, with deterministic ties and unknowns last
      // in both directions. Different offsets must compare as instants.
      var accounts = [
        {providerId:"claude-low", limits:[{label:"Fable Weekly",percent:0.1,resetsAt:"2026-09-20T12:00:00Z"}]},
        {providerId:"claude-high", limits:[{label:"Fable Weekly",percent:0.9,resetsAt:"2026-09-20T09:00:00+02:00"}]},
        {providerId:"claude-tie", limits:[{label:"Fable Weekly",percent:0.1,resetsAt:"invalid"}]},
        {providerId:"claude-missing", limits:[{label:"weekly",percent:0.4}]}
      ]
      function ids(rows) { return rows.map(function(row) {return row.providerId}).join(",") }
      check(ids(panel.sortAccounts(accounts,"usage-asc")) === "claude-low,claude-tie,claude-high,claude-missing", "Least used order incorrect")
      check(ids(panel.sortAccounts(accounts,"usage-desc")) === "claude-high,claude-low,claude-tie,claude-missing", "Most used order incorrect")
      check(ids(panel.sortAccounts(accounts,"reset-asc")) === "claude-high,claude-low,claude-tie,claude-missing", "Soonest reset order incorrect")
      check(ids(panel.sortAccounts(accounts,"reset-desc")) === "claude-low,claude-high,claude-tie,claude-missing", "Latest reset order incorrect")
      check(ids(panel.sortAccounts(accounts,"default")) === "claude-low,claude-high,claude-tie,claude-missing", "Default order changed")
      check(ids(accounts) === "claude-low,claude-high,claude-tie,claude-missing", "Sorting mutated source accounts")
      panel.selectCompany(0)
      panel.showDetails(0)
      var selectedId = panel.provider.providerId
      overviewDialog.open("anthropic", "Anthropic", panel.overviewOptions, "fable weekly", "default")
      var sortField = find(overviewDialog,"overviewSort")
      check(sortField.value === "default" && sortField.options.length === 5, "Sort choices missing")
      sortField.value = "usage-asc"
      overviewDialog.canceled()
      check(panel.overviewSort("anthropic") === "default", "Cancel saved a sort")
      overviewDialog.open("anthropic", "Anthropic", panel.overviewOptions, "fable weekly", "default")
      sortField.value = "usage-asc"
      overviewDialog.submit()
      check(!overviewDialog.opened && panel.providers[0].providerId === "claude-work", "Saved sort did not reorder actual accounts")
      check(panel.provider.providerId === selectedId, "Sorting switched selected account")
      panel.settings = test.original
      check(panel.overviewSort("anthropic") === "usage-asc", "Reload lost sorting preference")
      check(panel.overviewSort("openai") === "default" && panel.overviewSort("xai") === "default", "Sort leaked across providers")
      check(saved.providers.claude.name === "Updated personal" && saved.overviewMetrics.anthropic === "fable weekly", "Sort overwrote existing settings")
      running = false
      finish.start()
    }
  }
}
