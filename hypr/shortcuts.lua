-- Loaded by Omarchy (default/hypr/dictation-backend.lua) while Dictate Review is the
-- default dictation backend. Omarchy itself binds Alt+Space and Alt+Right Alt to it.

-- Keep Superwhisper's own shortcuts (Ctrl+Alt+Space, its overlays' layer rules)
-- working alongside: Omarchy only loads the selected backend's file.
local sw = os.getenv("HOME") .. "/.config/superwhisper/shortcuts.lua"
local f = io.open(sw, "r")
if f then
  f:close()
  local ok, err = pcall(dofile, sw)
  if not ok then print("dictate-review: could not load Superwhisper shortcuts: " .. tostring(err)) end
end

-- The glow animates itself; Hyprland's layer fade would hold it back.
hl.layer_rule({ match = { namespace = "^dictate-glow$" }, no_anim = true, animation = "none" })

-- The user's toggle keybind: "keybind" in ~/.config/dictate-review/config.json
-- (`dictate-review keybind "CHORD"` sets it and reloads). Default replaces
-- Omarchy's ALT+SPACE dictation binding (and Superwhisper's ALT+space above)
-- with left Ctrl + left Alt + Space.
local chord = "CTRL + ALT + SPACE"
local cf = io.open(os.getenv("HOME") .. "/.config/dictate-review/config.json", "r")
if cf then
  local body = cf:read("*a")
  cf:close()
  chord = body:match('"keybind"%s*:%s*"([^"]+)"') or chord
end
if chord:match("^%s*$") then chord = "CTRL + ALT + SPACE" end
local function norm(s) return s:upper():gsub("%s+", "") end
if norm(chord) ~= "ALT+SPACE" then
  hl.unbind("ALT + SPACE")
end
local function bind_toggle(c)
  return hl.bind(c, hl.dsp.exec_cmd("dictate-review toggle"), { description = "Toggle dictation" })
end
local toggle_bind = bind_toggle(chord)

-- Live keybind capture (panel Keybind row → `dictate-review keybind --capture`):
-- with a capture pending, the next non-modifier key press with its held
-- modifiers becomes the new chord. Escape cancels.
local state = os.getenv("HOME") .. "/.local/state/dictate-review"
local capture_req = state .. "/capture.request"
local modname = { [42] = "SHIFT", [54] = "SHIFT", [29] = "CTRL", [97] = "CTRL",
                  [56] = "ALT", [100] = "ALT", [125] = "SUPER", [126] = "SUPER" }
local keyname = { [57] = "SPACE", [28] = "RETURN", [15] = "TAB", [14] = "BACKSPACE", [1] = "ESCAPE",
                  [59]="F1",[60]="F2",[61]="F3",[62]="F4",[63]="F5",[64]="F6",[65]="F7",[66]="F8",[67]="F9",[68]="F10",[87]="F11",[88]="F12",
                  [12]="MINUS",[13]="EQUAL",[26]="LEFTBRACKET",[27]="RIGHTBRACKET",[43]="BACKSLASH",
                  [39]="SEMICOLON",[40]="APOSTROPHE",[41]="GRAVE",[51]="COMMA",[52]="DOT",[53]="SLASH" }
for c, n in pairs({ A=30,S=31,D=32,F=33,G=34,H=35,J=36,K=37,L=38,Q=16,W=17,E=18,R=19,T=20,Y=21,U=22,I=23,O=24,P=25,Z=44,X=45,C=46,V=47,B=48,N=49,M=50 }) do
  keyname[c] = n
end
for i = 0, 9 do keyname[2 + i] = tostring((i + 1) % 10) end
local held = {}
local function save_keybind(c)
  local f = io.open(os.getenv("HOME") .. "/.config/dictate-review/config.json", "r")
  local body = f and f:read("*a") or nil
  if f then f:close() end
  if body and body:match('"keybind"') then
    body = body:gsub('("keybind"%s*:%s*")[^"]*"', "%1" .. c .. '"')
  elseif body and body:match("%S") then
    body = body:gsub("%s*}%s*$", ',\n  "keybind": "' .. c .. '"\n}')
  else
    body = '{\n  "keybind": "' .. c .. '"\n}\n'
  end
  local t = io.open(os.getenv("HOME") .. "/.config/dictate-review/config.json", "w")
  if t then t:write(body); t:close() end
end
local function capturing()
  local f = io.open(capture_req, "r")
  if f then f:close(); return true end
  return false
end
local function say(msg)
  os.execute("notify-send -a 'Dictate Review' 'Dictate Review' " .. string.format("%q", msg) .. " >/dev/null 2>&1 &")
end
hl.on("input.keyboard.key", function(code, time, kstate)
  local ev = code - 8                              -- XKB code → evdev code
  if modname[ev] then held[modname[ev]] = kstate == 1 and true or nil; return end
  if kstate ~= 1 or not capturing() then return end
  local name = keyname[ev]
  if not name then return end
  if toggle_bind then toggle_bind:set_enabled(false) end
  os.remove(capture_req)
  if name == "ESCAPE" then
    if toggle_bind then toggle_bind:set_enabled(true) end
    say("Keybind unchanged")
    return
  end
  local mods = {}
  for _, m in ipairs({ "CTRL", "ALT", "SHIFT", "SUPER" }) do
    if held[m] then mods[#mods + 1] = m end
  end
  mods[#mods + 1] = name
  local newchord = table.concat(mods, " + ")
  if norm(newchord) ~= norm(chord) then
    hl.unbind(chord)
    toggle_bind = bind_toggle(newchord)
    chord = newchord
    save_keybind(newchord)
  else
    if toggle_bind then toggle_bind:set_enabled(true) end
  end
  say("Dictate keybind: " .. newchord)
end)

-- Review popup: small floating card (it places itself above the target window), on every workspace.
o.window("^(dev\\.dictatereview\\.popup)$", {
  float = true,
  pin = true,
  no_anim = true,
  size = { 560, 230 },
})
