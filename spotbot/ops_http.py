"""Read-only ops page for the spot bot.

Binds 127.0.0.1:19280. Ports 18180-18182 belong to the DUP mesh and are refused.
The page does not send orders and does not read API keys.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MESH_PORTS = frozenset({18180, 18181, 18182})
DEFAULT_PORT = 19280

_HIDDEN = ("api_key", "api_secret", "secret", "token", "password")


class OpsError(RuntimeError):
    """Refused ops bind."""


def parse_ops_port(raw: object) -> int:
    """A short digit string only. A name, a fraction, or a huge integer is not a port."""
    if not isinstance(raw, str):
        raise OpsError("ops port must be an integer")
    text = raw.strip()
    if len(text) > 5 or not text.isdigit():
        raise OpsError("ops port must be an integer")
    port = int(text)
    check_ops_port(port)
    return port


def check_ops_port(port: int) -> None:
    if isinstance(port, bool) or not isinstance(port, int):
        raise OpsError("ops port must be an integer")
    if port in MESH_PORTS:
        raise OpsError(f"refusing port {port}: 18180-18182 is the DUP mesh")
    if port < 1024 or port > 65535:
        raise OpsError("ops port must be 1024..65535")


def snapshot(data_dir: Path, port: int = DEFAULT_PORT) -> dict[str, object]:
    """Public view of books, quotes, events, and the bot log."""
    if not isinstance(data_dir, Path) or not data_dir.is_dir():
        return {
            "bind": f"127.0.0.1:{port}",
            "mesh_ports": "18180-18182",
            "books": {"error": "data dir is not a directory"},
            "quotes": {},
            "events": [],
            "log": [],
            "heartbeat": None,
        }
    books: dict[str, object] = {}
    names = ("sleeve_major", "sleeve_alt", "sleeve_meme", "book", "book_liquidity", "treasury")
    for folder in ("", "paper", "live"):
        base = data_dir if folder == "" else data_dir / folder
        for name in names:
            path = base / f"{name}.json"
            if not path.exists():
                continue
            key = name if folder == "" else f"{folder}/{name}"
            try:
                too_big = path.stat().st_size > 1_000_000
            except OSError:
                books[key] = {"error": "book is not json"}
                continue
            if too_big:
                books[key] = {"error": "book file is too large"}
                continue
            loaded = _read_json(path)
            if not isinstance(loaded, dict):
                books[key] = {"error": "book is not json"}
                continue
            books[key] = _show_book(loaded)
    return {
        "bind": f"127.0.0.1:{port}",
        "mesh_ports": "18180-18182",
        "books": books,
        "quotes": _quotes(data_dir),
        "events": _events(data_dir),
        "log": _log_tail(data_dir / "ops.log"),
        "heartbeat": _heartbeat(data_dir),
    }


def _status_bytes(data_dir: Path, port: int, limit: int = 1_000_000) -> bytes:
    """The status page stays under a megabyte. A larger body is not sent."""
    try:
        body = json.dumps(snapshot(data_dir, port), ensure_ascii=False).encode("utf-8")
    except (OSError, UnicodeError, ValueError, TypeError, RecursionError, MemoryError) as exc:
        raise OpsError("status unreadable") from exc
    if len(body) > limit:
        raise OpsError("status unreadable")
    return body


def _ops_path(raw: object) -> str | None:
    """The page path only. A long query is not read as a route."""
    if not isinstance(raw, str) or len(raw) > 256:
        return None
    return raw.split("?", 1)[0]


def serve(data_dir: Path, port: int = DEFAULT_PORT) -> None:
    check_ops_port(port)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    httpd.data_dir = data_dir  # type: ignore[attr-defined]
    httpd.serve_forever()


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802
        path = _ops_path(self.path)
        if path is None:
            self._send(404, "text/plain; charset=utf-8", b"not found")
            return
        if path == "/api/status":
            data_dir = self.server.data_dir  # type: ignore[attr-defined]
            port = int(self.server.server_address[1])
            try:
                body = _status_bytes(data_dir, port)
            except OpsError:
                self._send(500, "text/plain; charset=utf-8", b"status unreadable")
                return
            self._send(200, "application/json; charset=utf-8", body)
            return
        if path in ("/", "/index.html"):
            self._send(200, "text/html; charset=utf-8", _PAGE.encode("utf-8"))
            return
        self._send(404, "text/plain; charset=utf-8", b"not found")

    def do_POST(self) -> None:  # noqa: N802
        self._send(405, "text/plain; charset=utf-8", b"read only")

    do_PUT = do_POST
    do_DELETE = do_POST
    do_PATCH = do_POST

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def _send(self, code: int, content_type: str, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)


def _show_book(loaded: object) -> object:
    """Prices and cash leave the page as text. A raw integer does not survive in the browser."""
    view = _public(loaded)
    if not isinstance(view, dict) or not isinstance(loaded, dict):
        return view
    for key in ("cash_micro", "realized_micro", "fees_micro", "funded_micro", "guard_cash_micro"):
        if key in view:
            view[key] = _money_text(view[key])
    positions = view.get("positions")
    if not isinstance(positions, list) or len(positions) > 8:
        if isinstance(positions, list):
            view["positions"] = "unreadable"
        return view
    from spotbot.money import format_price

    legacy = "price_scale" not in loaded
    for index, pos in enumerate(positions):
        if not isinstance(pos, dict) or len(pos) > 16:
            positions[index] = "unreadable"
            continue
        if "quote_micro" in pos:
            pos["quote_micro"] = _money_text(pos["quote_micro"])
        if "base_atoms" in pos:
            pos["base_atoms"] = _coin_text(pos["base_atoms"])
        for key in ("entry_micro", "peak_micro"):
            raw = pos.get(key)
            if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0 or raw >= 10**24:
                pos[key] = "unreadable"
                continue
            shown = raw * 1_000_000 if legacy else raw
            if shown >= 10**24:
                pos[key] = "unreadable"
                continue
            pos[key] = format_price(shown)
    return view


def _coin_text(raw: object) -> str:
    """Coin size as text. A raw atom count is not sent to the browser."""
    from spotbot.money import BASE_ATOMS, MoneyError, format_fixed

    if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0 or raw >= 10**24:
        return "unreadable"
    try:
        return format_fixed(raw, BASE_ATOMS)
    except MoneyError:
        return "unreadable"


def _money_text(raw: object) -> str:
    """USDT text for the page. A bool or a fraction is not a balance."""
    from spotbot.money import format_usdt

    if isinstance(raw, bool) or not isinstance(raw, int) or raw <= -10**24 or raw >= 10**24:
        return "unreadable"
    return format_usdt(raw)


def _public(value: object, depth: int = 0) -> object:
    if depth >= 8:
        return "unreadable"
    if isinstance(value, str):
        return value if len(value) <= 180 else value[:180]
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int):
        if value <= -10**24 or value >= 10**24:
            return "unreadable"
        return value
    if isinstance(value, dict):
        if len(value) > 64:
            return "unreadable"
        return {
            key: _public(item, depth + 1)
            for key, item in value.items()
            if isinstance(key, str) and not _hidden(key)
        }
    if isinstance(value, list):
        if len(value) > 32:
            return "unreadable"
        return [_public(item, depth + 1) for item in value]
    return "unreadable"


def _hidden(key: str) -> bool:
    low = key.lower()
    return any(part in low for part in _HIDDEN)


def _read_json(path: Path) -> object | None:
    """None when the file cannot be read. One bad file must not blank the page."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, MemoryError, RecursionError):
        return None


def _heartbeat(data_dir: Path) -> dict[str, object] | None:
    path = data_dir / "ops_heartbeat.json"
    if not path.exists():
        return None
    try:
        if path.stat().st_size > 1_000_000:
            return None
    except OSError:
        return None
    loaded = _read_json(path)
    if not isinstance(loaded, dict) or len(loaded) > 8:
        return None
    stamp = loaded.get("at")
    if not isinstance(stamp, str) or not stamp or len(stamp) > 40:
        return None
    from datetime import datetime

    try:
        then = datetime.fromisoformat(stamp)
        if then.tzinfo is None:
            return None
        age = int((datetime.now().astimezone() - then).total_seconds())
    except (TypeError, ValueError, OverflowError):
        return None
    if age < 0 or age > 86_400 * 366:
        return None
    book = loaded.get("book")
    if not isinstance(book, str) or len(book) > 32:
        book = ""
    return {"at": stamp, "book": book, "age_sec": age}


def _quotes(data_dir: Path) -> dict[str, object]:
    path = data_dir / "ops_quotes.json"
    if not path.exists():
        return {}
    try:
        if path.stat().st_size > 1_000_000:
            return {}
    except OSError:
        return {}
    loaded = _read_json(path)
    if not isinstance(loaded, dict) or len(loaded) > 32:
        return {}
    return {
        key: _public(value)
        for key, value in loaded.items()
        if isinstance(key, str) and len(key) <= 32 and isinstance(_public(value), (dict, str, int))
    }


def _tail_text(path: Path, limit: int) -> str:
    """The end of a journal. A long file is not loaded whole into the page."""
    size = path.stat().st_size
    with path.open("rb") as handle:
        if size > limit:
            handle.seek(size - limit)
        raw = handle.read().decode("utf-8", errors="replace")
    if size > limit:
        raw = raw.split("\n", 1)[-1]
    return raw


def _events(data_dir: Path) -> list[object]:
    path = data_dir / "ops_events.jsonl"
    if not path.exists():
        return []
    rows: list[object] = []
    try:
        text = _tail_text(path, 65_536)
    except OSError:
        return []
    for line in text.splitlines():
        if not line.strip() or len(line) > 4_096:
            continue
        try:
            item = json.loads(line)
        except (json.JSONDecodeError, RecursionError, MemoryError):
            continue
        if isinstance(item, dict):
            shown = _public(item)
            if isinstance(shown, dict):
                rows.append(shown)
    return rows[-50:]


def _log_tail(path: Path) -> list[str]:
    if not path.exists():
        return []
    try:
        lines = _tail_text(path, 65_536).splitlines()
    except OSError:
        return []
    kept = [line if len(line) <= 240 else line[:240] for line in lines if _safe_log(line)]
    return kept[-40:]


def _safe_log(line: str) -> bool:
    low = line.lower()
    return "api_key" not in low and "api_secret" not in low and "telegram_token" not in low


_PAGE = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DUP spot ops</title>
<style>
  body { margin: 0; font: 14px/1.4 ui-sans-serif, sans-serif; background: #121417; color: #e7e4dc; }
  header, main { padding: 16px 20px; }
  header { border-bottom: 1px solid #2a2e33; }
  h1 { font-size: 18px; margin: 0 0 6px; }
  h2 { font-size: 15px; margin: 18px 0 8px; }
  p { margin: 0; color: #a8a294; }
  table { width: 100%; border-collapse: collapse; }
  th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid #2a2e33; vertical-align: top; }
  th { color: #a8a294; font-weight: 600; }
  .neg { color: #e07a72; }
  pre { white-space: pre-wrap; background: #1b1e22; padding: 10px; }
</style>
</head>
<body>
<header>
  <h1>Спот-бот, ops</h1>
  <p id="bind">локальная страница, mesh не трогает</p>
  <p id="entries">новые покупки выключены, продаётся только уже открытая монета</p>
  <p id="beat">цикл ещё не завершался</p>
</header>
<main>
  <h2>Книги</h2>
  <table id="books"><tbody><tr><td>нет книг</td></tr></tbody></table>
  <h2>Цены, последняя сверка</h2>
  <table id="quotes"><tbody><tr><td>бот ещё не сверял</td></tr></tbody></table>
  <h2>Сделки</h2>
  <table id="events"><tbody><tr><td>сделок нет</td></tr></tbody></table>
  <h2>Журнал</h2>
  <pre id="log">пусто</pre>
</main>
<script>
async function tick() {
  const res = await fetch("/api/status", { cache: "no-store" });
  const data = await res.json();
  document.getElementById("bind").textContent =
    "http://" + data.bind + "  ·  mesh " + data.mesh_ports + " не используется";
  const beat = data.heartbeat;
  document.getElementById("beat").textContent = beat
    ? "последний цикл " + beat.book + " " + beat.at + " · " + beat.age_sec + " с назад"
    : "цикл ещё не завершался";
  document.getElementById("books").innerHTML = renderBooks(data.books || {});
  document.getElementById("quotes").innerHTML = renderQuotes(data.quotes || {});
  document.getElementById("events").innerHTML = renderEvents(data.events || []);
  document.getElementById("log").textContent = (data.log || []).join("\\n") || "пусто";
}
function esc(value) {
  return String(value == null ? "" : value).replace(/[&<>"']/g, function (ch) {
    return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[ch];
  });
}
function renderBooks(books) {
  const names = Object.keys(books);
  if (!names.length) return "<tbody><tr><td>нет книг</td></tr></tbody>";
  let html = "<thead><tr><th>книга</th><th>USDT</th><th>результат</th><th>комиссия</th><th>позиции</th></tr></thead><tbody>";
  for (const name of names) {
    const book = books[name];
    if (!book || typeof book !== "object") {
      html += "<tr><td>" + esc(name) + "</td><td colspan='4'>" + esc(book) + "</td></tr>";
      continue;
    }
    if (book.error) {
      html += "<tr><td>" + esc(name) + "</td><td colspan='4'>" + esc(book.error) + "</td></tr>";
      continue;
    }
    if (name === "treasury" || name.endsWith("/treasury")) {
      html += "<tr><td>" + esc(name) + "</td><td colspan='4'>уже разделено " + esc(money(book.funded_micro)) + "</td></tr>";
      continue;
    }
    let pos = "—";
    if (book.positions === "unreadable") pos = "не читается";
    else if (Array.isArray(book.positions)) {
      pos = book.positions.map(function (p) {
        if (!p || typeof p !== "object") return "не читается";
        const size = p.base_atoms == null ? "" : " " + esc(p.base_atoms);
        const cost = p.quote_micro == null ? "" : " · " + esc(money(p.quote_micro));
        const held = p.hold_flat === true ? " · удержание, ниже себестоимости не продаётся" : "";
        const lot = p.below_lot === true ? " · меньше шага лота, продажа не уходит" : "";
        return esc(p.symbol) + size + " @ " + esc(shown(p.entry_micro)) + cost + held + lot;
      }).join(", ") || "—";
    }
    html += "<tr><td>" + esc(name) + "</td><td>" + esc(money(book.cash_micro)) + "</td><td>" + esc(money(book.realized_micro)) +
      "</td><td>" + esc(money(book.fees_micro)) + "</td><td>" + pos + "</td></tr>";
  }
  return html + "</tbody>";
}
function renderQuotes(quotes) {
  const names = Object.keys(quotes);
  if (!names.length) return "<tbody><tr><td>бот ещё не сверял</td></tr></tbody>";
  let html = "<thead><tr><th>пара</th><th>MEXC</th><th>Binance</th><th>Bybit</th><th>OKX</th><th>lag</th><th>ширина</th><th>когда</th></tr></thead><tbody>";
  for (const name of names) {
    const q = quotes[name];
    if (!q || typeof q !== "object") {
      html += "<tr><td>" + esc(name) + "</td><td colspan='7'>не читается</td></tr>";
      continue;
    }
    html += "<tr><td>" + esc(name) + "</td><td>" + esc(q.mexc) + "</td><td>" + esc(q.binance) + "</td><td>" + esc(q.bybit) +
      "</td><td>" + esc(q.okx) + "</td><td>" + esc(q.lag_bps) + "</td><td>" + esc(q.width_bps) + "</td><td>" + esc(q.at) + "</td></tr>";
  }
  return html + "</tbody>";
}
function renderEvents(events) {
  if (!events.length) return "<tbody><tr><td>сделок нет</td></tr></tbody>";
  let html = "<thead><tr><th>когда</th><th>книга</th><th>что</th><th>пара</th><th>цена</th><th>зачислено</th><th>причина</th></tr></thead><tbody>";
  for (const ev of events.slice().reverse()) {
    if (!ev || typeof ev !== "object") continue;
    html += "<tr><td>" + esc(ev.at) + "</td><td>" + esc(ev.book) + "</td><td>" + esc(ev.kind) +
      "</td><td>" + esc(ev.symbol) + "</td><td>" + esc(ev.price) + "</td><td>" + esc(ev.credit == null ? "—" : ev.credit) +
      "</td><td>" + esc(ev.reason) + (ev.left === true ? " · остаток на книге" : "") + "</td></tr>";
  }
  return html + "</tbody>";
}
function shown(value) {
  if (typeof value === "string") return value;
  return money(value);
}
function money(value) {
  if (typeof value === "string") return value;
  return usdt(value);
}
function usdt(micro) {
  if (typeof micro === "boolean" || micro === undefined || micro === null) return "—";
  const n = Number(micro);
  const sign = n < 0 ? "-" : "";
  const abs = Math.abs(n);
  const whole = Math.floor(abs / 1000000);
  const frac = String(abs % 1000000).padStart(6, "0");
  return sign + whole + "." + frac;
}
tick();
setInterval(tick, 3000);
</script>
</body>
</html>
"""
