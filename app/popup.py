#!/usr/bin/env python3
"""Review popup: shows the transcript with low-confidence words coloured, lets you fix
them, then pastes the text into the window you were dictating into.

Keys: Tab / Shift+Tab next/previous flagged word · Enter paste · Shift+Enter newline
      Esc discard · Ctrl+R send the same audio to Deepgram again
"""
import json, os, re, subprocess, sys, time
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gdk, Gio, GLib, Pango

APP_ID = "dev.dictatereview.popup"          # Hyprland window class (see the window rule)
HOME = os.path.expanduser("~")
STATE = os.path.join(HOME, ".local/state/dictate-review")
CLI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dictate_review.py")


def theme():
    c = {"background": "#1a1b26", "foreground": "#a9b1d6", "accent": "#7aa2f7", "red": "#f7768e",
         "yellow": "#e0af68", "lighter_background": "#24283b", "dark_foreground": "#565f89", "selection": "#292e42"}
    try:
        for line in open(os.path.join(HOME, ".local/state/omarchy/current/theme/colors.toml")):
            m = re.match(r'\s*(\w+)\s*=\s*"(#[0-9a-fA-F]{6})"', line)
            if m:
                c[m[1]] = m[2]
    except OSError:
        pass
    return c


def font():
    try:
        return subprocess.run(["omarchy-font-current"], capture_output=True, text=True, timeout=2).stdout.strip() or "monospace"
    except Exception:
        return "monospace"


class Popup:
    def __init__(self, app, data):
        self.app, self.data = app, data
        self.result = None                     # text to paste, or None
        c = theme()
        self.c = c
        css = Gtk.CssProvider()
        css.load_from_string(f"""
          window.dr {{ background: {c['background']}; border: 2px solid {c['accent']}; }}
          window.dr * {{ font-family: "{font()}"; }}
          .dr-head {{ color: {c['dark_foreground']}; font-size: 11px; }}
          .dr-head .lang {{ color: {c['accent']}; font-weight: bold; }}
          textview.dr-text, textview.dr-text text {{ background: {c['lighter_background']}; color: {c['foreground']};
                                                    font-size: 15px; caret-color: {c['accent']}; }}
          textview.dr-text text selection {{ background: {c['red']}; color: {c['background']}; }}
          .dr-text-frame {{ border: 1px solid {c['selection']}; }}
          .dr-foot {{ color: {c['dark_foreground']}; font-size: 11px; }}
          .dr-error {{ color: {c['red']}; font-size: 14px; }}
        """)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css, 800)

        win = Gtk.ApplicationWindow(application=app, title="Dictate Review")
        win.add_css_class("dr")
        win.set_default_size(560, 230)
        win.set_decorated(False)
        self.win = win
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        for side in ("top", "bottom", "start", "end"):
            getattr(box, f"set_margin_{side}")(12)
        win.set_child(box)

        target = data.get("target") or {}
        lang = {"en": "EN", "pt": "PT"}.get(data.get("language"), "EN")
        head = Gtk.Box(spacing=8)
        head.add_css_class("dr-head")
        l1 = Gtk.Label(label="󰍬 Dictate Review", xalign=0); l1.set_hexpand(True)
        l2 = Gtk.Label(label=lang); l2.add_css_class("lang")
        l3 = Gtk.Label(label="→ " + (target.get("class") or "clipboard"))
        for w in (l1, l2, l3):
            head.append(w)
        box.append(head)

        if data.get("error"):
            err = Gtk.Label(label=data["error"] + "\nYour audio is kept.", xalign=0, wrap=True)
            err.add_css_class("dr-error"); err.set_vexpand(True); err.set_valign(Gtk.Align.START)
            box.append(err)
            foot_text = "Ctrl+R retry · Esc close"
            self.view = None
        else:
            self.view = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, left_margin=10, right_margin=10,
                                     top_margin=8, bottom_margin=8, has_tooltip=True)
            self.view.add_css_class("dr-text")
            sc = Gtk.ScrolledWindow(); sc.set_child(self.view); sc.set_vexpand(True); sc.add_css_class("dr-text-frame")
            box.append(sc)
            self.fill()
            foot_text = "Tab next flagged · Enter paste · Shift+Enter newline · Esc discard · Ctrl+R retry"
        foot = Gtk.Label(label=foot_text, xalign=0)
        foot.add_css_class("dr-foot")
        box.append(foot)

        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self.on_key)
        win.add_controller(keys)
        win.set_opacity(0.01)                  # practically invisible until it's moved into place (0 would never map)
        win.present()
        GLib.timeout_add(40, self.place, 0)
        if self.view:
            self.view.grab_focus()
            GLib.idle_add(self.jump, 1, True)

    def place(self, tries):
        """Put the popup just above the bottom of the window you dictated into (where chat
        and terminal inputs live), centred on it and kept on that monitor."""
        try:
            clients = json.loads(subprocess.run(["hyprctl", "-j", "clients"], capture_output=True, text=True).stdout)
            me = next((c for c in clients if c.get("pid") == os.getpid()), None)
            if not me:
                if tries < 25:
                    GLib.timeout_add(40, self.place, tries + 1); return False
                raise LookupError
            t = self.data.get("target") or {}
            tw = next((c for c in clients if c.get("address") == t.get("address")), None) or t
            if tw.get("at") and tw.get("size"):
                pw, ph = me["size"]
                (tx, ty), (tw_, th) = tw["at"], tw["size"]
                mons = json.loads(subprocess.run(["hyprctl", "-j", "monitors"], capture_output=True, text=True).stdout)
                m = next((m for m in mons if m["id"] == tw.get("monitor")), mons[0])
                mx, my = m["x"], m["y"]
                mw, mh = m["width"] / m["scale"], m["height"] / m["scale"]
                x = tx + (tw_ - pw) / 2
                y = ty + th - ph - 64
                x = max(mx + 8, min(x, mx + mw - pw - 8))
                y = max(my + 8, min(y, my + mh - ph - 8))
                subprocess.run(["hyprctl", "dispatch",
                                f'hl.dsp.window.move({{ x = {int(x)}, y = {int(y)}, window = "address:{me["address"]}" }})'],
                               capture_output=True)
        except Exception:
            pass
        GLib.timeout_add(30, lambda: (self.win.set_opacity(1), False)[1])
        return False

    # ---- text with tags ----
    def fill(self):
        buf = self.view.get_buffer()
        self.buf = buf
        c = self.c
        self.t_low = buf.create_tag("low", foreground=c["red"], weight=Pango.Weight.BOLD,
                                    underline=Pango.Underline.ERROR, underline_rgba=self.rgba(c["red"]))
        self.t_mid = buf.create_tag("mid", foreground=c["yellow"], weight=Pango.Weight.BOLD)
        self.conf = {}
        low, mid = self.data.get("low", 0.6), self.data.get("mid", 0.85)
        for i, w in enumerate(self.data.get("words", [])):
            if i:
                buf.insert(buf.get_end_iter(), " ")
            tags = []
            if w["confidence"] < mid:
                t = buf.create_tag(f"w{i}")
                self.conf[f"w{i}"] = w["confidence"]
                tags = [self.t_low if w["confidence"] < low else self.t_mid, t]
            buf.insert_with_tags(buf.get_end_iter(), w["word"], *tags)
        self.original = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        buf.connect("changed", lambda b: GLib.idle_add(self.clear_at_cursor))
        self.view.connect("query-tooltip", self.on_tooltip)

    @staticmethod
    def rgba(hexs):
        r = Gdk.RGBA(); r.parse(hexs); return r

    def clear_at_cursor(self):
        """A word you've edited stops being flagged."""
        it = self.buf.get_iter_at_mark(self.buf.get_insert())
        for probe in (it.copy(), self._back(it)):
            for tag in (self.t_low, self.t_mid):
                if probe.has_tag(tag):
                    s, e = probe.copy(), probe.copy()
                    if not s.starts_tag(tag):
                        s.backward_to_tag_toggle(tag)
                    e.forward_to_tag_toggle(tag)
                    self.buf.remove_tag(tag, s, e)
        return False

    @staticmethod
    def _back(it):
        b = it.copy(); b.backward_char(); return b

    def ranges(self):
        out = []
        for tag in (self.t_low, self.t_mid):
            it = self.buf.get_start_iter()
            while it.starts_tag(tag) or it.forward_to_tag_toggle(tag):
                if it.starts_tag(tag):
                    e = it.copy(); e.forward_to_tag_toggle(tag)
                    out.append((it.get_offset(), e.get_offset(), tag is self.t_low))
                    it = e
                elif it.is_end():
                    break
        return sorted(out)

    def jump(self, direction=1, first=False):
        rs = self.ranges()
        if not rs:
            if first:
                self.buf.place_cursor(self.buf.get_end_iter())
            return False
        if first:                                   # start on the first red word, else the first yellow
            pick = next((r for r in rs if r[2]), rs[0])
        else:
            cur = self.buf.get_iter_at_mark(self.buf.get_insert()).get_offset()
            if direction > 0:
                pick = next((r for r in rs if r[0] > cur), rs[0])
            else:
                sel = self.buf.get_selection_bounds()
                cur = sel[0].get_offset() if sel else cur
                pick = next((r for r in reversed(rs) if r[0] < cur), rs[-1])
        s = self.buf.get_iter_at_offset(pick[0]); e = self.buf.get_iter_at_offset(pick[1])
        self.buf.select_range(e, s)                 # cursor at start, typing replaces the word
        self.view.scroll_to_iter(s, 0.1, False, 0, 0)
        return False

    def on_tooltip(self, view, x, y, keyboard, tip):
        bx, by = view.window_to_buffer_coords(Gtk.TextWindowType.WIDGET, x, y)
        ok, it = view.get_iter_at_location(bx, by)
        if not ok:
            return False
        for t in it.get_tags():
            name = t.get_property("name") or ""
            if name in self.conf:
                tip.set_text(f"confidence {self.conf[name]:.2f}")
                return True
        return False

    # ---- keys ----
    def on_key(self, ctl, keyval, code, mods):
        shift = bool(mods & Gdk.ModifierType.SHIFT_MASK)
        ctrl = bool(mods & Gdk.ModifierType.CONTROL_MASK)
        if keyval == Gdk.KEY_Escape:
            self.close(None); return True
        if ctrl and keyval in (Gdk.KEY_r, Gdk.KEY_R):
            self.close(None)
            subprocess.Popen(["/usr/bin/python3", "-I", CLI, "retry"], start_new_session=True)
            return True
        if not self.view:
            return False
        if keyval in (Gdk.KEY_Tab, Gdk.KEY_ISO_Left_Tab):
            self.jump(-1 if (shift or keyval == Gdk.KEY_ISO_Left_Tab) else 1); return True
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and not shift:
            text = self.buf.get_text(self.buf.get_start_iter(), self.buf.get_end_iter(), False).strip()
            self.log_edit(text)
            self.close(text or None); return True
        return False

    def log_edit(self, final):
        try:
            with open(os.path.join(STATE, "edits.jsonl"), "a") as f:
                f.write(json.dumps({"t": time.time(), "words": self.data.get("words", []),
                                    "original": self.original, "final": final}) + "\n")
        except OSError:
            pass

    def close(self, text):
        self.result = text
        self.win.close()
        self.app.quit()


# ---------- paste back into the saved window ----------
def paste(text, data):
    from dictate_review import conf, notify
    c = conf()
    target = data.get("target") or {}
    addr = target.get("address")
    clients = json.loads(subprocess.run(["hyprctl", "-j", "clients"], capture_output=True, text=True).stdout or "[]")
    exists = any(cl.get("address") == addr for cl in clients) if addr else False

    old = None
    try:
        types = subprocess.run(["wl-paste", "--list-types"], capture_output=True, text=True, timeout=2).stdout
        if "text/plain" in types:
            old = subprocess.run(["wl-paste", "--no-newline"], capture_output=True, timeout=2).stdout
    except Exception:
        pass
    subprocess.run(["wl-copy", "--", text])
    if not exists:
        notify("The window you dictated into is gone. The text is on your clipboard.")
        return
    subprocess.run(["hyprctl", "dispatch", f'hl.dsp.focus({{ window = "address:{addr}" }})'], capture_output=True)
    time.sleep(0.15)
    cls = target.get("class") or ""
    tags = [t.rstrip("*") for t in (target.get("tags") or [])]
    chord = c["paste_chords"].get(cls) or ("ctrl+shift+v" if ("terminal" in tags or cls in c["terminal_classes"]) else "ctrl+v")
    mods = chord.split("+")[:-1]; key = chord.split("+")[-1]
    cmd = ["wtype"]
    for m in mods: cmd += ["-M", m]
    cmd += ["-k", key]
    for m in reversed(mods): cmd += ["-m", m]
    subprocess.run(cmd)
    if old is not None:                         # give the app time to read it, then restore
        time.sleep(0.8)
        subprocess.run(["wl-copy"], input=old)


def main():
    data = json.load(open(sys.argv[1]))
    app = Gtk.Application(application_id=APP_ID, flags=Gio.ApplicationFlags.NON_UNIQUE)
    holder = {}
    app.connect("activate", lambda a: holder.setdefault("p", Popup(a, data)))
    app.run([])
    p = holder.get("p")
    if p and p.result:
        sys.path.insert(0, os.path.dirname(CLI))
        paste(p.result, data)


if __name__ == "__main__":
    main()
