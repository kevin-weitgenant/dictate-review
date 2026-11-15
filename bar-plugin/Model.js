// Pure helpers, kept apart from the QML so they are easy to test.

function parseStatus(raw) {
  try {
    var parsed = JSON.parse(String(raw || "").trim())
    return parsed && typeof parsed === "object" ? parsed : null
  } catch (e) {
    return null
  }
}

function stateLabel(phase) {
  if (phase === "recording") return "Recording"
  if (phase === "working") return "Transcribing"
  return ""
}

function seconds(value) {
  var n = Number(value)
  if (!isFinite(n) || n <= 0) return ""
  return n < 10 ? n.toFixed(1) + "s" : Math.round(n) + "s"
}

function ago(createdAt, nowSec) {
  var then = Number(createdAt)
  if (!isFinite(then) || then <= 0) return ""
  var delta = Math.max(0, Math.floor(nowSec - then))
  if (delta < 60) return "just now"
  if (delta < 3600) return Math.floor(delta / 60) + "m ago"
  if (delta < 86400) return Math.floor(delta / 3600) + "h ago"
  return Math.floor(delta / 86400) + "d ago"
}

// "30 words · 16s · 6 flagged · edited"
function statsLine(last) {
  if (!last) return ""
  var parts = []
  var words = Number(last.words || 0)
  if (words > 0) parts.push(words + (words === 1 ? " word" : " words"))
  var audio = seconds(last.seconds)
  if (audio) parts.push(audio)
  var flagged = Number(last.flagged || 0)
  if (flagged > 0) parts.push(flagged + " flagged")
  if (last.edited) parts.push("edited")
  return parts.join(" · ")
}

function usageLine(minutes, cost) {
  var m = Number(minutes || 0)
  var c = Number(cost || 0)
  return (m < 10 ? m.toFixed(1) : Math.round(m)) + " min · $" + c.toFixed(2)
}
