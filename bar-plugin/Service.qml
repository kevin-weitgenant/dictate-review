import QtQuick
import Quickshell
import Quickshell.Io
import "Model.js" as Model

// Follows `dictate-review status --follow`, which prints one JSON line each
// time anything changes (phase, language, last dictation, usage), so the bar
// is live without polling here.
Item {
  id: root

  readonly property string cli: Quickshell.env("HOME") + "/.local/bin/dictate-review"
  readonly property string configPath: Quickshell.env("HOME") + "/.config/dictate-review/config.json"

  property bool connected: false
  property string phase: "idle"
  property string language: "en"
  property string languageLabel: "English"
  property string model: "nova-3"
  property string keybind: "CTRL + ALT + SPACE"
  property bool capturing: false
  property var last: null
  property real monthMinutes: 0
  property real monthCostUsd: 0
  property bool copied: false

  readonly property bool recording: phase === "recording"
  readonly property bool working: phase === "working"

  function _same(a, b) { return JSON.stringify(a) === JSON.stringify(b) }

  function apply(line) {
    var s = Model.parseStatus(line)
    if (!s) return
    connected = true
    phase = String(s.phase || "idle")
    language = String(s.language || "en")
    languageLabel = String(s.languageLabel || "")
    model = String(s.model || "")
    keybind = String(s.keybind || keybind)
    capturing = s.capturing === true
    var l = s.last && s.last.created ? s.last : null
    if (!_same(last, l)) last = l
    monthMinutes = Number(s.monthMinutes || 0)
    monthCostUsd = Number(s.monthCostUsd || 0)
  }

  function run(args) { Quickshell.execDetached([cli].concat(args)) }

  // Drawn at once; the next status line confirms it.
  function setLanguage(value) {
    if (value === language) return
    language = value
    languageLabel = value === "pt" ? "Português" : "English"
    run(["language", value])
  }
  function toggleLanguage() { setLanguage(language === "en" ? "pt" : "en") }
  function toggleDictation() { run(["toggle"]) }
  function cancel() { run(["cancel"]) }
  function reopen() { run(["reopen"]) }
  function retry() { run(["retry"]) }
  function setKeybind(chord) { run(["keybind", chord]) }
  function captureKeybind() { run(["keybind", "--capture"]) }
  function openConfig() { Quickshell.execDetached(["omarchy-launch-editor", configPath]) }

  function copyLast() {
    if (!last || !last.text) return
    Quickshell.execDetached(["wl-copy", "--", String(last.text)])
    copied = true
    copiedTimer.restart()
  }

  Timer {
    id: copiedTimer
    interval: 1500
    onTriggered: root.copied = false
  }

  Process {
    id: follow
    command: [root.cli, "status", "--follow"]
    running: true
    stdout: SplitParser {
      onRead: function(line) { root.apply(line) }
    }
    onExited: { root.connected = false; restart.start() }
  }

  // If the follower dies (an update, a crash), start it again.
  Timer {
    id: restart
    interval: 2000
    onTriggered: follow.running = true
  }
}
