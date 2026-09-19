import QtQuick
import qs.Commons
import qs.Ui

FocusScope {
  id: root
  property bool opened: false
  property string accountId: ""
  property string errorText: ""
  property color foreground: Color.foreground
  property string fontFamily: Style.font.family
  readonly property real minimumHeight: form.implicitHeight + Style.space(48)
  signal canceled()
  signal saveRequested(string accountId, string name)
  visible: opened

  function open(account) {
    accountId = account.providerId
    accountName.text = account.providerName
    errorText = ""
    opened = true
    Qt.callLater(function() {
      accountName.forceActiveFocus()
      accountName.selectAll()
    })
  }
  function close() { opened = false }
  function submit() {
    if (accountName.text.trim() !== "") root.saveRequested(accountId, accountName.text.trim())
  }
  Keys.onEscapePressed: root.canceled()

  Rectangle {
    anchors.fill: parent
    color: Util.alpha(Color.background, 0.85)
    MouseArea { anchors.fill: parent; onClicked: root.canceled() }
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
        text: "Edit account name"
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.title
        font.bold: true
      }
      TextField {
        id: accountName
        objectName: "editAccountName"
        width: parent.width
        maximumLength: 80
        placeholderText: "Account name"
        foreground: root.foreground
        font.family: root.fontFamily
        onTextEdited: root.errorText = ""
        onAccepted: root.submit()
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
          onClicked: root.canceled()
        }
        Button {
          text: "Save"
          bordered: true
          selected: true
          focusable: true
          foreground: root.foreground
          fontFamily: root.fontFamily
          enabled: accountName.text.trim() !== ""
          opacity: enabled ? 1 : 0.5
          onClicked: root.submit()
        }
      }
    }
  }
}
