#!/usr/bin/env python3
"""Dictate Review: record → Deepgram (per-word confidence) → review popup → paste back.

Commands:
  toggle | start | stop | cancel   recording control (start/stop also for push-to-talk)
  retry                            send the last recording to Deepgram again
  reopen                           show the last result again
  language [en|pt|toggle]          show or set the dictation language
  keybind [CHORD]                 show or set the toggle keybind (Hyprland syntax, e.g. "CTRL + ALT + SPACE")
  status [--follow]                JSON for the bar widget
  transcribe FILE.wav              print words and confidences (testing)
"""
import json, os, re, signal, subprocess, sys, time, urllib.error, urllib.parse, urllib.request

HOME = os.path.expanduser("~")
APP = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HOME, ".local/state/dictate-review")
CONF = os.path.join(HOME, ".config/dictate-review/config.json")
SECRETS = os.path.join(HOME, ".config/env/secrets.sh")
PY = "/usr/bin/python3"

DEFAULTS = {
    "language": "en",                 # en | pt   (switch from the bar or `dictate-review language`)
    "model": "nova-3",
    "low": 0.60,                      # below: red
    "mid": 0.85,                      # below: yellow
    "terminal_classes": ["herdr-app"],  # paste with Ctrl+Shift+V (plus anything tagged "terminal")
    "paste_chords": {},               # per window class override, e.g. {"foo": "ctrl+v"}
    "extra_keyterms": [],
    "max_seconds": 300,
    "keybind": "CTRL + ALT + SPACE",  # toggle-dictation chord (Hyprland syntax); rebinds on reload
}
LANGS = {"en": ("en", "English"), "pt": ("pt-BR", "Português")}

os.makedirs(STATE, exist_ok=True)
P = lambda n: os.path.join(STATE, n)


# ---------- small helpers ----------
def conf():
    c = dict(DEFAULTS)
    try:
        c.update(json.load(open(CONF)))
    except (OSError, ValueError):
        pass
    return c


def save_conf(c):
    os.makedirs(os.path.dirname(CONF), exist_ok=True)
    user = {k: v for k, v in c.items() if DEFAULTS.get(k) != v}
    tmp = CONF + ".tmp"
    json.dump(user, open(tmp, "w"), indent=2)
    os.replace(tmp, CONF)


def notify(msg, urgency="normal"):
    subprocess.Popen(["notify-send", "-a", "Dictate Review", "-u", urgency, "Dictate Review", msg],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def hypr(cmd):
    try:
        return json.loads(subprocess.run(["hyprctl", "-j", cmd], capture_output=True, text=True, timeout=3).stdout or "{}")
    except Exception:
        return {}


def alive(pid):
    try:
        os.kill(pid, 0)
        return open(f"/proc/{pid}/cmdline", "rb").read().find(b"glow.py") >= 0
    except (OSError, ValueError):
        return False


def glow_pid():
    try:
        pid = int(open(P("glow.pid")).read())
        return pid if alive(pid) else None
    except (OSError, ValueError):
        return None


def set_phase(phase):
    open(P("phase.tmp"), "w").write(phase)
    os.replace(P("phase.tmp"), P("phase"))


def phase():
    try:
        ph = open(P("phase")).read().strip()
    except OSError:
        return "idle"
    if ph in ("recording", "working") and not glow_pid():
        return "idle"
    return ph or "idle"


def api_key():
    k = os.environ.get("DEEPGRAM_API_KEY")
    if k:
        return k
    try:
        for line in open(SECRETS):
            m = re.match(r'\s*(?:export\s+)?DEEPGRAM_API_KEY\s*=\s*["\']?([^"\'\s#]+)', line)
            if m:
                return m.group(1)
    except OSError:
        pass
    return None


def vocabulary(c):
    terms = list(c.get("extra_keyterms", []))
    try:
        out = subprocess.run(["superwhisper", "vocab", "show"], capture_output=True, text=True, timeout=4).stdout
        terms += json.loads(out).get("config", {}).get("terms", [])
    except Exception:
        pass
    seen, uniq = set(), []
    for t in terms:
        if t and t.lower() not in seen:
            seen.add(t.lower()); uniq.append(t)
    return uniq[:100]


# ---------- Deepgram ----------
def transcribe(wav, c=None):
    c = c or conf()
    key = api_key()
    if not key:
        raise RuntimeError("DEEPGRAM_API_KEY not found (environment or ~/.config/env/secrets.sh)")
    lang = LANGS.get(c["language"], LANGS["en"])[0]
    params = [("model", c["model"]), ("smart_format", "true"), ("punctuate", "true"), ("language", lang)]
    terms = vocabulary(c)
    data = open(wav, "rb").read()

    def call(with_terms):
        q = params + ([("keyterm", t) for t in terms] if with_terms else [])
        req = urllib.request.Request("https://api.deepgram.com/v1/listen?" + urllib.parse.urlencode(q), data=data,
                                     headers={"Authorization": "Token " + key, "Content-Type": "audio/wav"})
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.load(r)

    try:
        res = call(bool(terms))
    except urllib.error.HTTPError as e:
        if e.code == 400 and terms:          # some languages don't take keyterms: retry without
            res = call(False)
        else:
            raise RuntimeError(f"Deepgram HTTP {e.code}: {e.read()[:200].decode(errors='replace')}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Couldn't reach Deepgram ({e.reason})")
    alt = res["results"]["channels"][0]["alternatives"][0]
    words = [{"word": w.get("punctuated_word") or w["word"], "confidence": round(w.get("confidence", 1.0), 3),
              "start": w.get("start"), "end": w.get("end")} for w in alt.get("words", [])]
    dur = res.get("metadata", {}).get("duration", 0)
    return {"transcript": alt.get("transcript", ""), "words": words, "duration": dur, "language": c["language"]}


def wav_seconds(path):
    try:
        import wave
        with wave.open(path) as w:
            return w.getnframes() / w.getframerate()
    except Exception:
        return 0.0


# ---------- commands ----------
def start():
    if glow_pid():
        return
    c = conf()
    win = hypr("activewindow")
    target = {k: win.get(k) for k in ("address", "class", "title", "tags", "at", "size", "monitor")} if win else {}
    json.dump(target, open(P("target.json"), "w"))
    for f in ("last.wav", "last.wav.done"):
        try: os.remove(P(f))
        except OSError: pass
    log = open(P("glow.log"), "w")
    args = [PY, "-I", os.path.join(APP, "glow.py"), str(c["max_seconds"]), "--out", P("last.wav")]
    if target.get("address"):
        args += ["--target", target["address"]]
    g = subprocess.Popen(args,
                         stdout=log, stderr=log, start_new_session=True)
    open(P("glow.pid"), "w").write(str(g.pid))
    open(P("started"), "w").write(str(time.time()))
    set_phase("recording")


def stop():
    pid = glow_pid()
    if not pid:
        return
    os.kill(pid, signal.SIGUSR1)                       # stop recording, glow → working
    set_phase("working")
    for _ in range(60):
        if os.path.exists(P("last.wav.done")):
            break
        time.sleep(0.05)
    secs = wav_seconds(P("last.wav"))
    end_glow(pid)                                      # the glow goes away the moment you stop
    if secs < 0.3:
        set_phase("idle"); return
    finish()


def end_glow(pid):
    try: os.kill(pid, signal.SIGTERM)
    except OSError: return
    for _ in range(40):
        if not alive(pid):
            return
        time.sleep(0.025)
    try: os.kill(pid, signal.SIGKILL)
    except OSError: pass


def finish(pid=None):
    c = conf()
    target = {}
    try: target = json.load(open(P("target.json")))
    except (OSError, ValueError): pass
    try:
        result = transcribe(P("last.wav"), c)
        result["error"] = None if result["words"] else "Didn't catch anything."
    except Exception as e:
        result = {"transcript": "", "words": [], "error": str(e), "language": c["language"]}
    result.update(target=target, low=c["low"], mid=c["mid"], created=time.time(), seconds=wav_seconds(P("last.wav")))
    json.dump(result, open(P("last.json"), "w"))
    if not result["error"]:
        flagged = sum(1 for w in result["words"] if w["confidence"] < c["mid"])
        with open(P("usage.jsonl"), "a") as u:
            u.write(json.dumps({"t": time.time(), "seconds": round(result["seconds"], 2), "words": len(result["words"]),
                                "flagged": flagged, "language": c["language"]}) + "\n")
    if pid:
        try: os.kill(pid, signal.SIGTERM)
        except OSError: pass
        for _ in range(40):                         # the glow must be gone before the popup shows
            if not alive(pid):
                break
            time.sleep(0.025)
        else:
            try: os.kill(pid, signal.SIGKILL)
            except OSError: pass
    set_phase("idle")
    open_popup()


def open_popup():
    subprocess.Popen([PY, "-I", os.path.join(APP, "popup.py"), P("last.json")],
                     stdout=open(P("popup.log"), "w"), stderr=subprocess.STDOUT, start_new_session=True)


def cancel():
    pid = glow_pid()
    if pid:
        try: os.kill(pid, signal.SIGTERM)
        except OSError: pass
    set_phase("idle")


def toggle():
    stop() if glow_pid() else start()


def retry():
    if not os.path.exists(P("last.wav")):
        notify("No recording to retry."); return
    finish()


def language(arg=None):
    c = conf()
    if arg in ("toggle", "next"):
        arg = "pt" if c["language"] == "en" else "en"
    if arg:
        if arg not in LANGS:
            sys.exit(f"unknown language {arg!r}; use en or pt")
        c["language"] = arg
        save_conf(c)
    print(c["language"])


def keybind(arg=None):
    c = conf()
    if arg == "--capture":
        os.makedirs(STATE, exist_ok=True)
        open(P("capture.request"), "w").write(str(time.time()))
        notify("Press the key combo for dictation… (Escape cancels)")
        return
    if arg:
        c["keybind"] = arg
        save_conf(c)
        try:                                  # shortcuts.lua re-reads it and rebinds
            subprocess.run(["hyprctl", "reload"], capture_output=True, timeout=5)
        except Exception:
            pass
    print(c["keybind"])


def last_edit():
    try:
        with open(P("edits.jsonl"), "rb") as f:
            f.seek(0, 2); f.seek(max(0, f.tell() - 65536))
            lines = f.read().splitlines()
        return json.loads(lines[-1]) if lines else None
    except (OSError, ValueError):
        return None


def status_obj():
    c = conf()
    last = {}
    try:
        lj = json.load(open(P("last.json")))
        last = {"text": " ".join(w["word"] for w in lj.get("words", [])) or lj.get("error") or "",
                "flagged": sum(1 for w in lj.get("words", []) if w["confidence"] < lj.get("mid", 0.85)),
                "low": sum(1 for w in lj.get("words", []) if w["confidence"] < lj.get("low", 0.6)),
                "words": len(lj.get("words", [])), "error": lj.get("error"), "created": lj.get("created"),
                "seconds": round(lj.get("seconds") or 0, 1), "edited": False}
        e = last_edit()                              # what was actually pasted, if it came from this dictation
        if e and e.get("t", 0) >= (lj.get("created") or 0) and e.get("final"):
            last["text"], last["edited"] = e["final"], e.get("final") != e.get("original")
    except (OSError, ValueError):
        pass
    month = time.strftime("%Y-%m")
    secs = 0.0
    try:
        for line in open(P("usage.jsonl")):
            u = json.loads(line)
            if time.strftime("%Y-%m", time.localtime(u["t"])) == month:
                secs += u["seconds"]
    except (OSError, ValueError):
        pass
    price = 0.0043 if c["language"] == "en" else 0.0052
    return {"phase": phase(), "language": c["language"], "languageLabel": LANGS[c["language"]][1], "model": c["model"],
            "keybind": c["keybind"], "capturing": os.path.exists(P("capture.request")),
            "last": last, "monthMinutes": round(secs / 60, 1), "monthCostUsd": round(secs / 60 * price, 2)}


def status(follow=False):
    if not follow:
        print(json.dumps(status_obj())); return
    prev, parent = None, os.getppid()
    while os.getppid() == parent:                     # the bar reloaded or quit: stop
        s = json.dumps(status_obj())
        if s != prev:
            try: print(s, flush=True)
            except BrokenPipeError: return
            prev = s
        time.sleep(0.25)


def main():
    a = sys.argv[1:] or ["toggle"]
    cmd = a[0]
    if cmd == "toggle": toggle()
    elif cmd == "start": start()
    elif cmd == "stop": stop()
    elif cmd == "cancel": cancel()
    elif cmd == "retry": retry()
    elif cmd == "reopen": open_popup()
    elif cmd == "language": language(a[1] if len(a) > 1 else None)
    elif cmd == "keybind": keybind(a[1] if len(a) > 1 else None)
    elif cmd == "status": status("--follow" in a)
    elif cmd == "transcribe":
        r = transcribe(a[1])
        for w in r["words"]:
            print(f'{w["confidence"]:.2f}  {w["word"]}')
    else:
        print(__doc__); sys.exit(1)


if __name__ == "__main__":
    main()
