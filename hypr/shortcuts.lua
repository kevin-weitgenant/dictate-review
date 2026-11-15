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

-- Review popup: small floating card (it places itself above the target window), on every workspace.
o.window("^(dev\\.dictatereview\\.popup)$", {
  float = true,
  pin = true,
  no_anim = true,
  size = { 560, 230 },
})
