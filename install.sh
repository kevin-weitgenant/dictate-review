#!/bin/bash
# Link Dictate Review into place (Omarchy). Re-run after moving the repo.
set -e
R="$(cd "$(dirname "$0")" && pwd)"

need=(python-gobject gtk4 gtk4-layer-shell wtype wl-clipboard pipewire)
missing=$(pacman -T "${need[@]}" || true)
[ -n "$missing" ] && echo "Install first: omarchy pkg add $missing" && exit 1

link() { mkdir -p "$(dirname "$2")"; [ -e "$2" ] && [ ! -L "$2" ] && mv "$2" "$2.bak"; ln -sfn "$1" "$2"; }
link "$R/app"                                  ~/.local/share/dictate-review
link "$R/bin/dictate-review"                   ~/.local/bin/dictate-review
link "$R/bin/omarchy-dictation-dictate-review" ~/.local/bin/omarchy-dictation-dictate-review
link "$R/hypr/shortcuts.lua"                   ~/.config/dictate-review/shortcuts.lua
link "$R/bar-plugin"                           ~/.config/omarchy/plugins/dictatereview.panel

echo dictate-review > "${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/defaults/dictation"
omarchy plugin enable dictatereview.panel --before omarchy.tray >/dev/null || true
grep -q DEEPGRAM_API_KEY ~/.config/env/secrets.sh 2>/dev/null || [ -n "$DEEPGRAM_API_KEY" ] \
  || echo "Add: export DEEPGRAM_API_KEY=... to ~/.config/env/secrets.sh"
echo "Done. Alt+Space to dictate."
