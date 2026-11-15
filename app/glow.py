#!/usr/bin/env python3
"""Voice-reactive recording glow: a click-through overlay around the active
Hyprland window, in the current Omarchy theme colours. It records the mic
itself, so the glow is calm while you're quiet and comes alive when you speak.

  glow.py [seconds] [--out FILE.wav] [--debug]
    seconds   run for N seconds (default: until SIGTERM / Ctrl+C)
    --out     also save the recording as a 16 kHz mono WAV
    --debug   print the voice level a few times a second
    --screen  glow along the bottom of the monitor instead of the active window
"""
import array, json, math, os, re, signal, subprocess, sys, time, wave

# gtk4-layer-shell must be loaded before libwayland-client: re-exec with LD_PRELOAD.
LIB = "/usr/lib/libgtk4-layer-shell.so"
if LIB not in os.environ.get("LD_PRELOAD", ""):
    os.environ["LD_PRELOAD"] = (LIB + " " + os.environ.get("LD_PRELOAD", "")).strip()
    os.execv(sys.executable, [sys.executable] + sys.argv)

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import Gtk, Gdk, Gio, GLib, Gtk4LayerShell as LS
import cairo

RATE = 16000
HEADROOM_DB, SPAN_DB = 4.0, 22.0      # voice starts 4 dB above the room; full at +26 dB
WAVE_LEN, WAVE_SPEED = 410.0, 280.0    # px, px/s — measured from Superwhisper
TARGET = None                          # window address to glow on (else the active window)
MODE = "window"                        # "window": bottom of the active window (like Superwhisper) · "screen": bottom of the monitor


def hypr(cmd):
    return json.loads(subprocess.run(["hyprctl", "-j", cmd], capture_output=True, text=True).stdout or "{}")


def theme_colors():
    p = os.path.expanduser("~/.local/state/omarchy/current/theme/colors.toml")
    c = {}
    try:
        for line in open(p):
            m = re.match(r'\s*(\w+)\s*=\s*"#([0-9a-fA-F]{6})"', line)
            if m:
                c[m[1]] = tuple(int(m[2][i:i + 2], 16) / 255 for i in (0, 2, 4))
    except OSError:
        pass
    return c.get("accent", (0.48, 0.64, 0.97)), c.get("bright_magenta", c.get("magenta", (0.73, 0.6, 0.97)))


class Mic:
    """pw-record → raw s16 mono on a pipe; computes a smoothed voice level and
    optionally writes the WAV that will go to Deepgram."""

    def __init__(self, out, debug):
        self.level = 0.0          # latest chunk loudness, 0..1
        self.bass = 0.0           # latest chunk low-frequency loudness, 0..1
        self._lp = 0.0
        self._floor = {}
        self._seen = {}
        self.debug = debug
        self.wav = None
        self.out = out
        if out:
            self.wav = wave.open(out, "wb")
            self.wav.setnchannels(1); self.wav.setsampwidth(2); self.wav.setframerate(RATE)
        self.proc = subprocess.Popen(
            ["pw-record", "--rate", str(RATE), "--channels", "1", "--format", "s16", "--raw", "-"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        os.set_blocking(self.proc.stdout.fileno(), False)
        GLib.io_add_watch(self.proc.stdout.fileno(), GLib.PRIORITY_HIGH, GLib.IO_IN | GLib.IO_HUP, self.on_data)
        self._last_print = 0

    def on_data(self, fd, cond):
        if getattr(self, "_closed", False):
            return False
        try:
            data = os.read(fd, 4096)
        except BlockingIOError:
            return True
        if not data:
            return False
        if self.wav and not getattr(self, "_closed", False):
            self.wav.writeframes(data)
        samples = array.array("h", data[: len(data) // 2 * 2])
        if samples:
            lp, acc_all, acc_bass = self._lp, 0.0, 0.0
            for v in samples:
                f = v / 32768
                lp += 0.09 * (f - lp)                  # one-pole low-pass ≈ 250 Hz: the "bass"
                acc_all += f * f
                acc_bass += lp * lp
            self._lp = lp
            n = len(samples)
            db_all = 20 * math.log10(math.sqrt(acc_all / n) + 1e-9)
            db_bass = 20 * math.log10(math.sqrt(acc_bass / n) + 1e-9)
            self.level = self._rel(db_all, "all")
            self.bass = self._rel(db_bass, "bass")
        if self.debug and time.monotonic() - self._last_print > 0.25:
            self._last_print = time.monotonic()
            print(f"level {self.level:4.2f} bass {self.bass:4.2f} " + "█" * int(self.level * 30), flush=True)
        return True

    def _rel(self, db, key):
        """Loudness relative to the room: the noise floor follows quiet moments
        quickly and rises only slowly, so speech stands out on any mic."""
        if db < -90:                        # digital silence while the stream starts
            return 0.0
        f = self._floor.get(key)
        n = self._seen[key] = self._seen.get(key, 0) + 1
        if f is None:
            f = db
        elif db < f:
            f += (db - f) * 0.35
        elif n < 10:                        # first ~second: settle on the room quickly
            f += (db - f) * 0.3
        else:
            f += min(db - f, 0.12)          # then only ~1 dB/s upward drift
        self._floor[key] = f
        return min(1.0, max(0.0, (db - f - HEADROOM_DB) / SPAN_DB))

    def close(self):
        if getattr(self, "_closed", False):
            return
        self._closed = True
        self.proc.terminate()
        try:
            self.proc.wait(1)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        if self.wav:
            self.wav.close()
            open(self.out + ".done", "w").close()      # tells dictate-review the WAV is complete


class Glow:
    def __init__(self, app, seconds, mic):
        self.mic = mic
        self.c1, self.c2 = theme_colors()
        self.t0 = self.last = time.monotonic()
        self.angle = 0.0          # gradient rotation
        self.energy = 0.0         # smoothed loudness: fast up (30 ms), slow down (120 ms)
        self.motion = 0.0         # how much loudness is changing; speeds the ripples
        self.prev = 0.0
        self.ph1 = self.ph2 = 0.0 # two oscillators (0.8 Hz, 1.13 Hz) that never line up
        self.phase = self.phase2 = 0.0   # travelling-wave phases
        self.working = False             # after stop: Deepgram is transcribing
        self.rect = None
        self.mon = None
        win = Gtk.ApplicationWindow(application=app)
        win.add_css_class("glow")
        css = Gtk.CssProvider()
        css.load_from_string("window.glow{background:transparent;}")
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css, 800)
        LS.init_for_window(win)
        LS.set_namespace(win, "dictate-glow")
        LS.set_layer(win, LS.Layer.OVERLAY)
        LS.set_keyboard_mode(win, LS.KeyboardMode.NONE)
        LS.set_exclusive_zone(win, -1)
        for e in (LS.Edge.TOP, LS.Edge.BOTTOM, LS.Edge.LEFT, LS.Edge.RIGHT):
            LS.set_anchor(win, e, True)
        self.area = Gtk.DrawingArea()
        self.area.set_draw_func(self.draw)
        win.set_child(self.area)
        self.win = win
        self.track()
        win.present()
        win.get_surface().set_input_region(cairo.Region())   # click-through
        self.area.add_tick_callback(lambda *a: (self.area.queue_draw(), True)[1])
        GLib.timeout_add(150, self.track)
        if seconds:
            GLib.timeout_add(int(seconds * 1000), app.quit)

    def track(self):
        w = None
        if TARGET:
            w = next((c for c in hypr("clients") or [] if c.get("address") == TARGET), None)
        if not w:
            w = hypr("activewindow")
        mons = {m["id"]: m for m in hypr("monitors") or []}
        m = mons.get(w.get("monitor")) if w else None
        if not w or not m:
            self.rect = None
            return True
        if self.mon != m["name"]:
            self.mon = m["name"]
            for gm in Gdk.Display.get_default().get_monitors():
                if gm.get_connector() == m["name"]:
                    LS.set_monitor(self.win, gm)
        if MODE == "window":
            self.rect = (w["at"][0] - m["x"], w["at"][1] - m["y"], w["size"][0], w["size"][1])
        else:                                   # bottom of the focused monitor
            sc = m["scale"]
            tr = m.get("transform", 0) % 2 == 1
            mw, mh = (m["height"], m["width"]) if tr else (m["width"], m["height"])
            self.rect = (0, 0, mw / sc, mh / sc)
        return True

    def draw(self, area, cr, W, H):
        cr.set_operator(cairo.OPERATOR_CLEAR); cr.paint(); cr.set_operator(cairo.OPERATOR_OVER)
        now = time.monotonic()
        dt, self.last = now - self.last, now
        t = now - self.t0
        dt = min(dt, 0.05)
        loud = 0.5 * self.mic.level + 0.5 * self.mic.bass if self.mic else 0.0
        self.motion = self.motion * math.exp(-dt / 0.25) + abs(loud - self.prev)
        self.prev = loud
        tau = 0.03 if loud > self.energy else 0.12
        self.energy += (loud - self.energy) * (1 - math.exp(-dt / tau))
        speed = 1 + 0.6 * min(self.motion, 1)
        self.ph1 = (self.ph1 + dt * 2 * math.pi * 0.8 * speed) % (2 * math.pi)
        self.ph2 = (self.ph2 + dt * 2 * math.pi * 1.13 * speed) % (2 * math.pi)
        e = math.tanh(1.3 * self.energy)                       # soft ceiling on loud peaks
        if not self.rect:
            return
        x, y, w, h = self.rect
        fade = min(1.0, t / 0.25)

        # Shape measured from Superwhisper's edge glow (recorded over a black window):
        #  - one accent colour, ~92% at the bottom edge, fading as (1 - d/L)^2
        #  - L (glow height) ≈ 53 px, a travelling wave of ±16 px, ~410 px long,
        #    moving right at ~280 px/s, plus a faint second ripple
        #  - side strips: full brightness up to ~64 px, gone by ~92 px, narrowing upward
        # Voice adds only a little: slightly taller waves that move a bit faster.
        if self.working:
            e = 0.0
        busy = 2.6 if self.working else 1.0                  # faster, flatter "working" shimmer
        self.phase += dt * busy * (1 + 0.30 * e) * 2 * math.pi * WAVE_SPEED / WAVE_LEN
        self.phase2 += dt * (1 + 0.30 * e) * 2 * math.pi * 110 / 260
        amp = 16.5 * (1 + 0.25 * e) * (0.6 if self.working else 1.0)
        mean = 53 + 3 * e
        bottom = y + h
        cr.set_operator(cairo.OPERATOR_LIGHTEN)                 # overlaps keep the brighter, like one glow
        R, G, B = self.c1
        A = 0.92 * fade

        def fall(stops_len, horizontal, x0, y0, length):
            # gradient (1 - d/L)^2 starting at the edge (x0, y0) and running `length` px inward
            if horizontal:
                g = cairo.LinearGradient(x0, 0, x0 + length, 0)
            else:
                g = cairo.LinearGradient(0, y0, 0, y0 - length)
            for k in range(stops_len + 1):
                u = k / stops_len
                g.add_color_stop_rgba(u, R, G, B, A * (1 - u) ** 2)
            return g

        # bottom glow: narrow columns, each with its own wave height
        col = 4
        xx = x
        while xx < x + w:
            cxm = xx + col / 2 - x
            L = mean + amp * math.sin(2 * math.pi * cxm / WAVE_LEN - self.phase) \
                     + 2.2 * math.sin(2 * math.pi * cxm / 260 - self.phase2)
            cr.set_source(fall(6, False, 0, bottom, L))
            cr.rectangle(xx, bottom - L, min(col, x + w - xx), L)
            cr.fill()
            xx += col

        # side strips climbing from the bottom corners
        step = 3
        for d in range(0, 93, step):
            wc = max(0.0, 75 - 0.86 * d) * (1 + 0.15 * e)    # strip width at this height
            if wc < 0.5:
                continue
            v = 1.0 if d < 64 else max(0.0, 1 - ((d - 64) / 28) ** 1.6)   # fade near the top
            if v <= 0:
                continue
            for side in (0, 1):
                ex = x if side == 0 else x + w
                g = cairo.LinearGradient(ex, 0, ex + (wc if side == 0 else -wc), 0)
                for k in range(7):
                    u = k / 6
                    g.add_color_stop_rgba(u, R, G, B, A * v * (1 - u) ** 2)
                cr.set_source(g)
                cr.rectangle(ex if side == 0 else ex - wc, bottom - d - step, wc, step)
                cr.fill()
        cr.set_operator(cairo.OPERATOR_OVER)

def main():
    args = sys.argv[1:]
    out = None
    if "--out" in args:
        i = args.index("--out"); out = args[i + 1]; del args[i:i + 2]
    debug = "--debug" in args
    global MODE, TARGET
    if "--target" in args:
        i = args.index("--target"); TARGET = args[i + 1]; del args[i:i + 2]
    if "--screen" in args:
        MODE = "screen"
    args = [a for a in args if a not in ("--debug", "--screen")]
    secs = float(args[0]) if args else 0
    app = Gtk.Application(application_id="dev.dictatereview.glow", flags=Gio.ApplicationFlags.NON_UNIQUE)
    state = {}

    def activate(a):
        state["mic"] = Mic(out, debug)
        state["glow"] = Glow(a, secs, state["mic"])
    app.connect("activate", activate)
    def working(*a):
        def go():
            if "mic" in state:
                state["mic"].close()
            if "glow" in state:
                state["glow"].working = True
            return False
        GLib.idle_add(go)
    signal.signal(signal.SIGUSR1, working)
    signal.signal(signal.SIGTERM, lambda *a: GLib.idle_add(app.quit))
    signal.signal(signal.SIGINT, lambda *a: GLib.idle_add(app.quit))
    app.run([])
    if "mic" in state:
        state["mic"].close()


if __name__ == "__main__":
    main()
