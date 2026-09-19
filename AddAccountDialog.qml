import QtQuick
import Quickshell.Io
import qs.Commons
import qs.Ui

FocusScope {
  id: root
  property bool opened: false
  property color foreground: Color.foreground
  property string fontFamily: Style.font.family
  property var providers: []
  property string errorText: ""
  readonly property string helperPath: decodeURIComponent(Qt.resolvedUrl("add_account.py").toString().replace(/^file:\/\//, ""))
  readonly property real minimumHeight: form.implicitHeight + Style.space(48)
  signal canceled()
  signal launched()
  visible: opened

  function open(company) {
    errorText = ""
    accountName.text = ""
    provider.value = ["anthropic", "openai", "xai"].indexOf(company) >= 0 ? company : "anthropic"
    opened = true
    if (providers.length === 0 && !providerLoader.running) providerLoader.running = true
    Qt.callLater(function() { accountName.forceActiveFocus() })
  }
  function close() {
    provider.close()
    opened = false
  }
  function submit() {
    if (launcher.running || accountName.text.trim() === "" || providers.length === 0) return
    errorText = ""
    launcher.command = ["python3", helperPath,
                        "launch", "--", provider.value, accountName.text.trim()]
    launcher.running = true
  }
  Keys.onEscapePressed: root.canceled()

  Process {
    id: providerLoader
    command: ["python3", root.helperPath, "providers"]
    stdout: StdioCollector {
      onStreamFinished: {
        try { root.providers = JSON.parse(text) }
        catch (e) { root.errorText = "Unable to load providers." }
      }
    }
  }
  Process {
    id: launcher
    stderr: StdioCollector { onStreamFinished: if (text.trim()) root.errorText = text.trim() }
    onExited: function(code) {
      if (code === 0) root.launched()
      else if (!root.errorText) root.errorText = "Unable to open the terminal. Please try again."
    }
  }

  Rectangle {
    anchors.fill: parent
    color: Util.alpha(Color.background, 0.85)
    MouseArea { anchors.fill: parent; onClicked: if (!launcher.running) root.canceled() }
  }
  BorderSurface {
    anchors.centerIn: parent
    width: parent.width - Style.space(16)
    height: form.implicitHeight + Style.space(32)
    color: Color.popups.background
    borderSpec: Border.flat(Color.accent, Style.normalBorderWidth)
    radius: Style.cornerRadius
    MouseArea { anchors.fill: parent }
    Column {
      id: form
      anchors.centerIn: parent
      width: parent.width - Style.space(32)
      spacing: Style.space(14)
      Text {
        text: "Add account"
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.title
        font.bold: true
      }
      Dropdown {
        id: provider
        width: parent.width
        label: "Provider"
        options: root.providers
        foreground: root.foreground
        fontFamily: root.fontFamily
        enabled: !launcher.running
        onChanged: root.errorText = ""
        onPopupOpenChanged: if (!popupOpen && root.opened) accountName.forceActiveFocus()
      }
      Column {
        width: parent.width
        spacing: Style.space(6)
        Text {
          text: "Account name"
          color: Qt.darker(root.foreground, 1.4)
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          font.bold: true
        }
        TextField {
          id: accountName
          width: parent.width
          placeholderText: "e.g. Work or Personal"
          maximumLength: 80
          foreground: root.foreground
          font.family: root.fontFamily
          enabled: !launcher.running
          onTextEdited: root.errorText = ""
          onAccepted: root.submit()
        }
      }
      Text {
        width: parent.width
        text: "A terminal will open to sign in. Your account will appear here when you're done."
        wrapMode: Text.WordWrap
        color: Qt.darker(root.foreground, 1.4)
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
      }
      Text {
        width: parent.width
        visible: text !== ""
        text: root.errorText
        textFormat: Text.PlainText
        wrapMode: Text.WordWrap
        color: Color.urgent
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
      }
      Row {
        anchors.right: parent.right
        spacing: Style.space(10)
        Button {
          text: "Cancel"
          bordered: true
          focusable: true
          foreground: root.foreground
          fontFamily: root.fontFamily
          enabled: !launcher.running
          onClicked: root.canceled()
        }
        Button {
          text: launcher.running ? "Opening…" : "Go"
          bordered: true
          selected: true
          focusable: true
          foreground: root.foreground
          fontFamily: root.fontFamily
          enabled: !launcher.running && accountName.text.trim() !== "" && root.providers.length > 0
          opacity: enabled ? 1 : 0.5
          onClicked: root.submit()
        }
      }
    }
  }
}
