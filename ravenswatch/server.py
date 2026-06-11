"""OBS Browser Source server for the melody overlay.

Serves a transparent, stream-ready HTML page showing the 3 run melodies
(unlock order) with icons, note-count color coding and an active indicator.
Add http://localhost:18904 as a Browser Source in OBS (suggested size
900x320, transparent background works out of the box).

Endpoints:
    /            HTML overlay page (polls /data every 2s)
    /data        JSON snapshot of the current run state
    /icons/<f>   melody icon PNGs (whitelisted)

A background thread polls game memory every POLL_INTERVAL seconds and keeps
a snapshot; HTTP requests never touch game memory directly, so any number of
browser sources can poll without piling up memory scans.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import process
from .melody_data import ICON_FILENAMES
from .memory import MemoryReader
from .resources import icons_dir

DEFAULT_PORT = 18904
POLL_INTERVAL = 3.0

_SERVABLE_ICONS = set(ICON_FILENAMES.values())

_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Ravenswatch Melodies</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  html, body { background: transparent; overflow: hidden; }
  body { font-family: "Segoe UI", Arial, sans-serif; -webkit-font-smoothing: antialiased; }
  #melodies {
    display: flex; justify-content: center; align-items: stretch;
    gap: 40px; padding: 28px 20px;
    opacity: 0; transition: opacity 0.5s ease;
  }
  #melodies.visible { opacity: 1; }
  .melody {
    display: flex; flex-direction: column; align-items: center;
    width: 250px; text-align: center;
  }
  .melody:not(.active) { opacity: 0.85; filter: saturate(0.85); }
  .melody.completed { opacity: 0.4; filter: grayscale(0.7); }
  .melody.completed .active-tag { visibility: visible; color: #9aa0b4; }
  .icon-wrap {
    position: relative; width: 112px; height: 112px;
    border-radius: 16px; padding: 6px;
    background: rgba(10, 12, 24, 0.82);
    border: 3px solid var(--note-color);
  }
  .melody.active .icon-wrap { animation: pulse 1.6s ease-in-out infinite; }
  @keyframes pulse {
    0%, 100% { box-shadow: 0 0 10px 2px var(--note-color); }
    50%      { box-shadow: 0 0 26px 8px var(--note-color); }
  }
  .icon-wrap img { width: 100%; height: 100%; }
  .slot {
    position: absolute; top: -12px; left: -12px;
    width: 30px; height: 30px; line-height: 30px; border-radius: 50%;
    background: var(--note-color); color: #0a0c18;
    font-size: 17px; font-weight: 800; text-align: center;
  }
  .name {
    margin-top: 12px;
    font-size: 26px; font-weight: 800; color: #ffffff;
    text-shadow: 0 0 6px #000, 0 2px 4px rgba(0, 0, 0, 0.9);
  }
  .pill {
    margin-top: 6px; padding: 2px 14px; border-radius: 999px;
    background: var(--note-color); color: #0a0c18;
    font-size: 16px; font-weight: 700;
  }
  .effect {
    margin-top: 8px;
    font-size: 17px; font-weight: 600; color: #e8e8f0;
    text-shadow: 0 0 5px #000, 0 2px 3px rgba(0, 0, 0, 0.9);
  }
  .active-tag {
    margin-top: 8px; font-size: 16px; font-weight: 800;
    color: #ffd76a; letter-spacing: 2px;
    text-shadow: 0 0 6px #000;
    visibility: hidden;
  }
  .melody.active .active-tag { visibility: visible; }
</style>
</head>
<body>
<div id="melodies"></div>
<script>
const NOTE_COLORS = { 4: "#16c79a", 5: "#f5a623", 6: "#e94560" };
const root = document.getElementById("melodies");
let lastKey = "";

function el(tagName, cls, text) {
  const e = document.createElement(tagName);
  e.className = cls;
  e.textContent = text;
  return e;
}

function render(data) {
  if (!data || !data.in_run || !data.melodies) {
    lastKey = "";
    root.classList.remove("visible");
    return;
  }
  const key = JSON.stringify(data.melodies);
  if (key === lastKey) return;  // avoid restarting the pulse animation
  lastKey = key;

  root.replaceChildren(...data.melodies.map(m => {
    const card = el("div",
      "melody" + (m.active ? " active" : "") + (m.completed ? " completed" : ""), "");
    card.style.setProperty("--note-color", NOTE_COLORS[m.notes] || "#ffffff");

    const wrap = el("div", "icon-wrap", "");
    if (m.icon) {
      const img = document.createElement("img");
      img.src = m.icon;
      img.alt = m.name;
      wrap.append(img);
    }
    const slot = el("div", "slot", m.slot);
    wrap.append(slot);

    card.append(
      wrap,
      el("div", "name", m.name),
      el("div", "pill", m.notes + " notes"),
      el("div", "effect", m.effect),
      el("div", "active-tag", m.completed ? "\\u2713 DONE" : "\\u266a ACTIVE \\u266a"),
    );
    return card;
  }));
  root.classList.add("visible");
}

async function tick() {
  try {
    const r = await fetch("/data", { cache: "no-store" });
    render(await r.json());
  } catch (e) {
    lastKey = "";
    root.classList.remove("visible");
  }
}
tick();
setInterval(tick, 2000);
</script>
</body>
</html>
"""


class _State:
    """Thread-safe snapshot of the current run, updated by the poller."""

    def __init__(self):
        self._lock = threading.Lock()
        self._snapshot = {"game_running": False, "in_run": False, "melodies": None}

    def update(self, snapshot: dict):
        with self._lock:
            self._snapshot = snapshot

    def get(self) -> dict:
        with self._lock:
            return self._snapshot


def _read_snapshot(reader: MemoryReader) -> dict:
    snap = {"game_running": process.is_running(), "in_run": False, "melodies": None}
    if not snap["game_running"]:
        reader.disconnect()
        return snap
    try:
        info = reader.read_run_info()
    except Exception:
        info = None
    if not info:
        return snap
    melodies, states = info
    snap["in_run"] = True
    snap["melodies"] = [
        {
            "slot": i + 1,
            "name": m.display_name,
            "internal_name": m.internal_name,
            "notes": m.notes,
            "effect": m.effect,
            "active": st == 1,
            "completed": st >= 2,
            "icon": f"/icons/{ICON_FILENAMES[m.display_name]}"
                    if m.display_name in ICON_FILENAMES else None,
        }
        for i, (m, st) in enumerate(zip(melodies, states))
    ]
    return snap


def _poll_loop(state: _State, stop: threading.Event):
    reader = MemoryReader()
    while not stop.is_set():
        state.update(_read_snapshot(reader))
        stop.wait(POLL_INTERVAL)
    reader.disconnect()


class _Handler(BaseHTTPRequestHandler):
    state: _State = None  # set on the subclass created in serve()

    def _send(self, status: int, content_type: str, body: bytes, cache: str = "no-store"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            self._send(200, "text/html; charset=utf-8", _PAGE.encode("utf-8"))
        elif path == "/data":
            self._send(200, "application/json", json.dumps(self.state.get()).encode("utf-8"))
        elif path.startswith("/icons/"):
            name = path[len("/icons/"):]
            icon_file = icons_dir() / name
            if name in _SERVABLE_ICONS and icon_file.exists():
                self._send(200, "image/png", icon_file.read_bytes(), cache="max-age=3600")
            else:
                self.send_error(404)
        else:
            self.send_error(404)

    def log_message(self, *args):
        pass  # keep the console quiet (and safe in windowed exe mode)


def serve(port: int = DEFAULT_PORT, host: str = "127.0.0.1"):
    """Run the OBS browser-source server until interrupted."""
    state = _State()
    stop = threading.Event()
    poller = threading.Thread(target=_poll_loop, args=(state, stop), daemon=True)
    poller.start()

    handler = type("Handler", (_Handler,), {"state": state})
    try:
        httpd = ThreadingHTTPServer((host, port), handler)
    except OSError as e:
        print(json.dumps({"error": f"Cannot bind {host}:{port}: {e}"}))
        raise SystemExit(1)

    shown_host = "localhost" if host in ("127.0.0.1", "0.0.0.0") else host
    print(json.dumps({
        "serving": f"http://{shown_host}:{port}",
        "obs": "Add as Browser Source, suggested size 900x320",
    }), flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        httpd.server_close()
