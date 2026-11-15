// Forked from the Superwhisper Omarchy panel (MIT, see LICENSE) and reworked
// for Dictate Review.
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "Model.js" as Model

Panel {
  id: root
  moduleName: "dictatereview"
  ipcTarget: "dictatereview"
  manageIpc: false

  property int rowIndex: 0
  property bool cursorActive: false
  property double nowSec: Date.now() / 1000

  readonly property color foreground: bar ? bar.foreground : Commons.Color.foreground
  readonly property color barFg: bar ? bar.barForeground : Commons.Color.foreground
  readonly property color urgent: bar ? bar.urgent : Commons.Color.urgent
  readonly property color accent: Commons.Color.accent
  readonly property color dim: Qt.darker(foreground, 1.55)
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family
  readonly property bool showLanguage: setting("showLanguage", true) !== false

  readonly property string micGlyph: "󰍬"
  readonly property color stateColor: dr.recording ? urgent : dr.working ? accent : barFg
  readonly property string liveState: Model.stateLabel(dr.phase)

  readonly property var rows: ["language", "dictate"]
    .concat(dr.last ? ["last", "retry"] : [])
    .concat(["config", "keybind"])
  readonly property string currentRow: cursorActive ? rows[Math.min(rowIndex, rows.length - 1)] : ""

  function moveCursor(dx, dy) {
    cursorActive = true
    if (dx !== 0 && currentRow === "language") { dr.setLanguage(dx < 0 ? "en" : "pt"); return }
    if (dy === 0) return
    rowIndex = Math.max(0, Math.min(rows.length - 1, rowIndex + dy))
  }

  function setRowCursor(id) {
    cursorActive = true
    rowIndex = Math.max(0, rows.indexOf(id))
  }

  function activate(id) {
    if (id === "language") dr.toggleLanguage()
    else if (id === "dictate") { root.close(); dr.toggleDictation() }
    else if (id === "last") { root.close(); dr.reopen() }
    else if (id === "retry") { root.close(); dr.retry() }
    else if (id === "config") { root.close(); dr.openConfig() }
    else if (id === "keybind") { dr.captureKeybind() }
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  property bool centredOnBar: false

  function inMiddleOfBar() {
    var window = root.QsWindow.window
    if (!window) return false
    var vertical = root.bar && root.bar.vertical
    var at = root.mapToItem(null, root.width / 2, root.height / 2)
    var span = vertical ? window.height : window.width
    var middle = vertical ? at.y : at.x
    return span > 0 && middle > span / 3 && middle < span * 2 / 3
  }

  function openPanel() {
    root.centredOnBar = root.inMiddleOfBar()
    root.open()
    if (root.centredOnBar) Qt.callLater(function() {
      if (root.opened && root.bar) root.bar.setCenterHoverRevealSuppressed(true)
    })
  }

  function togglePanel() {
    if (root.opened) root.close()
    else root.openPanel()
  }

  onOpenedChanged: if (!opened && centredOnBar && bar) {
    bar.setCenterHoverRevealSuppressed(false)
  } else if (opened) {
    cursorActive = false
    rowIndex = 0
    nowSec = Date.now() / 1000
    Qt.callLater(function() { keyCatcher.forceActiveFocus() })
  }

  Service { id: dr }
  property alias service: dr

  // omarchy-shell dictatereview toggle | language | dictate
  IpcHandler {
    target: root.ipcTarget
    function open(): void { root.openPanel() }
    function close(): void { root.close() }
    function toggle(): void { root.togglePanel() }
    function language(): string { dr.toggleLanguage(); return dr.language }
  }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.micGlyph
    labelText: root.showLanguage ? dr.language.toUpperCase() : ""
    foreground: root.stateColor
    useActiveColor: false
    tooltipText: "Dictate Review · " + dr.languageLabel
      + (root.liveState !== "" ? " · " + root.liveState : "")
      + "\nRight-click: switch EN/PT · Middle-click: dictate"

    // A slow breath while recording; steady otherwise.
    SequentialAnimation on opacity {
      running: dr.recording
      loops: Animation.Infinite
      onStopped: button.opacity = 1
      NumberAnimation { to: 0.45; duration: 700; easing.type: Easing.InOutSine }
      NumberAnimation { to: 1.0; duration: 700; easing.type: Easing.InOutSine }
    }

    onPressed: function(buttonCode) {
      if (buttonCode === Qt.RightButton) dr.toggleLanguage()
      else if (buttonCode === Qt.MiddleButton) dr.toggleDictation()
      else root.togglePanel()
    }
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    centerOnBar: root.centredOnBar
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(360))
    contentHeight: panel.fittedContentHeight(column.implicitHeight, Style.space(560))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onMoveRequested: function(dx, dy) {
        if (!root.cursorActive) { root.cursorActive = true; return }
        root.moveCursor(dx, dy)
      }
      onActivateRequested: if (root.cursorActive) root.activate(root.currentRow)
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onTextKey: function(t) {
        var key = t.toLowerCase()
        if (key === "c") dr.copyLast()
        else if (key === "l") dr.toggleLanguage()
        else if (key === "e") dr.setLanguage("en")
        else if (key === "p") dr.setLanguage("pt")
        else if (key === "d") root.activate("dictate")
        else if (key === "r") root.activate("retry")
        else if (key === "k") root.activate("keybind")
      }

      Column {
        id: column
        x: Style.space(2)
        width: parent.width - Style.space(4)
        spacing: Style.space(12)

        Hero { width: parent.width }

        PanelSeparator { foreground: root.foreground }

        Column {
          width: parent.width
          spacing: Style.space(6)

          LanguageRow { width: parent.width }

          ActionRow {
            rowId: "dictate"
            glyph: dr.recording ? "󰓛" : root.micGlyph
            label: dr.recording ? "Stop and review" : "Start dictation"
            hint: dr.keybind.replace(/\s*\+\s*/g, "+")
          }
        }

        PanelSeparator {
          visible: dr.last !== null
          foreground: root.foreground
        }

        Column {
          visible: dr.last !== null
          width: parent.width
          spacing: Style.space(6)

          LastDictation { width: parent.width }

          ActionRow {
            rowId: "retry"
            glyph: "󰑐"
            label: "Transcribe again"
            caption: "Sends the last recording to Deepgram again"
            hint: "R"
          }
        }

        PanelSeparator { foreground: root.foreground }

        Column {
          width: parent.width
          spacing: Style.space(6)

          // Read-only: what this month has cost so far.
          RowLayout {
            width: parent.width
            spacing: Style.space(8)

            Text {
              textFormat: Text.PlainText
              Layout.leftMargin: Style.space(10)
              text: "󰔵"
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.icon
            }
            Text {
              textFormat: Text.PlainText
              Layout.fillWidth: true
              text: "This month"
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.body
            }
            Text {
              textFormat: Text.PlainText
              Layout.rightMargin: Style.space(10)
              text: Model.usageLine(dr.monthMinutes, dr.monthCostUsd)
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.body
            }
          }

          ActionRow {
            rowId: "config"
            glyph: "󰒓"
            label: "Settings"
            caption: "config.json: thresholds, model, paste keys"
          }

          ActionRow {
            rowId: "keybind"
            glyph: "󰌓"
            label: dr.capturing ? "Press the combo…" : "Keybind"
            caption: dr.capturing ? "Escape cancels" : "Click, then press the keys you want (Hyprland syntax)"
            hint: dr.capturing ? "…" : dr.keybind.replace(/\s*\+\s*/g, "+")
          }
        }
      }
    }
  }

  Timer {
    interval: 30000
    repeat: true
    running: root.opened
    onTriggered: root.nowSec = Date.now() / 1000
  }

  component Hero: Item {
    id: heroRoot
    readonly property color heroDim: Qt.darker(root.foreground, 1.4)
    implicitHeight: Math.max(heroIcon.implicitHeight, heroLabels.implicitHeight)

    Text {
      id: heroIcon
      textFormat: Text.PlainText
      anchors.left: parent.left
      anchors.verticalCenter: parent.verticalCenter
      text: root.micGlyph
      color: dr.recording ? root.urgent : dr.working ? root.accent : root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.display
    }

    Column {
      id: heroLabels
      anchors.left: heroIcon.right
      anchors.leftMargin: Style.space(14)
      anchors.right: parent.right
      anchors.rightMargin: statePill.visible ? statePill.width + Style.space(8) : 0
      anchors.verticalCenter: parent.verticalCenter
      spacing: Style.space(2)

      Text {
        textFormat: Text.PlainText
        text: "Dictate Review"
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.subtitle
        font.bold: true
      }

      Text {
        textFormat: Text.PlainText
        width: parent.width
        text: (dr.connected ? "Deepgram " + dr.model + " · " + dr.languageLabel : "Not running").toUpperCase()
        color: heroRoot.heroDim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        font.bold: true
        font.letterSpacing: 1.2
        elide: Text.ElideRight
      }
    }

    BorderSurface {
      id: statePill
      visible: root.liveState !== ""
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      implicitWidth: pillText.implicitWidth + Style.space(10)
      implicitHeight: pillText.implicitHeight + Style.space(4)
      color: "transparent"
      borderSpec: Border.controlSpec("normal", root.foreground, dr.recording ? root.urgent : root.accent)
      radius: Style.cornerRadius

      Text {
        id: pillText
        textFormat: Text.PlainText
        anchors.centerIn: parent
        text: root.liveState
        color: dr.recording ? root.urgent : root.accent
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        font.bold: true
      }
    }
  }

  // "Language            [ EN ][ PT ]"  — click a side, or ←/→ on the row.
  component LanguageRow: CursorSurface {
    id: langRow
    hasCursor: root.currentRow === "language"
    foreground: root.foreground
    implicitHeight: langContent.implicitHeight + Style.spacing.rowPaddingX

    MouseArea {
      anchors.fill: parent
      hoverEnabled: true
      onEntered: root.setRowCursor("language")
    }

    RowLayout {
      id: langContent
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      anchors.leftMargin: Style.space(10)
      anchors.rightMargin: Style.space(10)
      spacing: Style.space(4)

      Text {
        textFormat: Text.PlainText
        Layout.fillWidth: true
        text: "Language"
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
      }

      Repeater {
        model: [{ value: "en", label: "English" }, { value: "pt", label: "Português" }]

        BorderSurface {
          required property var modelData
          readonly property bool selected: dr.language === modelData.value
          implicitWidth: segText.implicitWidth + Style.space(14)
          implicitHeight: segText.implicitHeight + Style.space(6)
          color: selected ? root.accent : "transparent"
          borderSpec: Border.controlSpec("normal", root.foreground, root.accent)
          radius: Style.cornerRadius

          Text {
            id: segText
            textFormat: Text.PlainText
            anchors.centerIn: parent
            text: parent.modelData.label
            color: parent.selected ? Commons.Color.background : root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
            font.bold: parent.selected
          }

          MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            onClicked: dr.setLanguage(parent.modelData.value)
          }
        }
      }
    }
  }

  component LastDictation: CursorSurface {
    id: lastRow
    hasCursor: root.currentRow === "last"
    foreground: root.foreground
    implicitHeight: lastContent.implicitHeight + Style.spacing.rowPaddingX * 2

    MouseArea {
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onEntered: root.setRowCursor("last")
      onClicked: root.activate("last")
    }

    ColumnLayout {
      id: lastContent
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      anchors.leftMargin: Style.space(10)
      anchors.rightMargin: Style.space(10)
      spacing: Style.space(4)

      Text {
        textFormat: Text.PlainText
        Layout.fillWidth: true
        text: dr.last ? (dr.last.error ? dr.last.error : dr.last.text) : ""
        color: dr.last && dr.last.error ? root.urgent : root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
        wrapMode: Text.WordWrap
        maximumLineCount: 3
        elide: Text.ElideRight
      }

      RowLayout {
        Layout.fillWidth: true
        spacing: Style.space(8)

        Text {
          textFormat: Text.PlainText
          Layout.fillWidth: true
          text: [Model.statsLine(dr.last), dr.last ? Model.ago(dr.last.created, root.nowSec) : ""]
                  .filter(function (part) { return part !== "" }).join(" · ")
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          elide: Text.ElideRight
        }

        Text {
          textFormat: Text.PlainText
          text: dr.copied ? "Copied" : "C copy"
          visible: lastRow.hasCursor || dr.copied
          color: dr.copied ? root.foreground : root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
        }
      }
    }
  }

  component ActionRow: CursorSurface {
    id: actionRow
    property string rowId: ""
    property string glyph: ""
    property string label: ""
    property string caption: ""
    property string hint: ""

    width: parent ? parent.width : implicitWidth
    hasCursor: root.currentRow === rowId
    foreground: root.foreground
    implicitHeight: actionContent.implicitHeight + Style.spacing.rowPaddingX

    MouseArea {
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onEntered: root.setRowCursor(actionRow.rowId)
      onClicked: root.activate(actionRow.rowId)
    }

    RowLayout {
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      anchors.leftMargin: Style.space(10)
      anchors.rightMargin: Style.space(10)
      spacing: Style.space(8)

      Text {
        textFormat: Text.PlainText
        text: actionRow.glyph
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.icon
        Layout.alignment: Qt.AlignVCenter
      }

      ColumnLayout {
        id: actionContent
        Layout.fillWidth: true
        spacing: Style.space(1)

        Text {
          textFormat: Text.PlainText
          Layout.fillWidth: true
          text: actionRow.label
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.body
          elide: Text.ElideRight
        }

        Text {
          textFormat: Text.PlainText
          Layout.fillWidth: true
          visible: actionRow.caption !== ""
          text: actionRow.caption
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          elide: Text.ElideRight
        }
      }

      Text {
        textFormat: Text.PlainText
        visible: actionRow.hint !== ""
        text: actionRow.hint
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        font.bold: true
        Layout.alignment: Qt.AlignVCenter
      }
    }
  }
}
