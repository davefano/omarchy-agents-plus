import QtQuick
import qs.Commons
import qs.Ui

FocusScope {
  id: root
  property bool opened: false
  property string companyId: ""
  property string companyName: ""
  property string errorText: ""
  property var sortOptions: []
  property color foreground: Color.foreground
  property string fontFamily: Style.font.family
  readonly property real minimumHeight: form.implicitHeight + Style.space(48)
  signal canceled()
  signal saveRequested(string companyId, string metric, string sort)
  visible: opened

  function open(company, name, options, selected, sort) {
    companyId = company
    companyName = name
    metric.options = options
    metric.value = selected
    sortOrder.value = sort || "default"
    errorText = ""
    opened = true
    Qt.callLater(function() { metric.nextItemInFocusChain().forceActiveFocus() })
  }
  function close() { metric.close(); sortOrder.close(); opened = false }
  function submit() { root.saveRequested(companyId, metric.value, sortOrder.value) }
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
        width: parent.width
        text: root.companyName + " settings"
        textFormat: Text.PlainText
        wrapMode: Text.WordWrap
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.title
        font.bold: true
      }
      Dropdown {
        id: metric
        objectName: "overviewMetric"
        width: parent.width
        label: "Show in overview"
        foreground: root.foreground
        fontFamily: root.fontFamily
        onChanged: root.errorText = ""
      }
      Dropdown {
        id: sortOrder
        objectName: "overviewSort"
        width: parent.width
        label: "Sort accounts"
        options: root.sortOptions
        foreground: root.foreground
        fontFamily: root.fontFamily
        onChanged: root.errorText = ""
      }
      Text {
        width: parent.width
        text: "Sorts by the usage limit selected above. Accounts with unavailable data appear last."
        textFormat: Text.PlainText
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
          onClicked: root.canceled()
        }
        Button {
          text: "Save"
          bordered: true
          selected: true
          focusable: true
          foreground: root.foreground
          fontFamily: root.fontFamily
          onClicked: root.submit()
        }
      }
    }
  }
}
