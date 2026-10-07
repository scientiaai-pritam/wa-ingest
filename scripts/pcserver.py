"""Static dashboard server + ticket-edit API. Serves dashboard/ on port 8765.

Endpoints:
  GET  /api/tickets          -> all tickets (JSON)
  GET  /api/systems          -> system id/name list (for the edit dropdown)
  POST /api/tickets/update   -> JSON {id, refs?, picked_by?, status?} — persists to
                                data/pcsystem.db AND pc_ticket_overrides.json so
                                daily rebuilds keep the manual corrections.
Run:  python scripts/pcserver.py     (hosts http://localhost:8765)
"""
import json, re, sys
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import pcsystem  # noqa: E402

OVERRIDES = ROOT / "data" / "structured" / "pc_ticket_overrides.json"


def db():
    con = pcsystem.connect()
    con.row_factory = sqlite3_Row
    return con


def sqlite3_Row(con):
    con.row_factory = sqlite3.Row
    return con


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT / "dashboard"), **kw)

    def log_message(self, fmt, *args):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        if self.path.startswith("/media/"):
            import mimetypes
            rel = self.path[len("/media/"):].split("?")[0]
            target = (ROOT / "data" / "media").joinpath(*rel.split("/")).resolve()
            mediaroot = (ROOT / "data" / "media").resolve()
            if not str(target).startswith(str(mediaroot)) or not target.is_file():
                return self._json({"error": "not found"}, 404)
            ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            body = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/api/tickets":
            con = pcsystem.connect()
            rows = [dict(r) for r in con.execute("SELECT * FROM tickets ORDER BY opened DESC, id DESC")]
            con.close()
            return self._json(rows)
        if self.path == "/api/systems":
            con = pcsystem.connect()
            rows = [dict(r) for r in con.execute("SELECT id, section, department, name FROM systems ORDER BY section, department, name")]
            con.close()
            return self._json(rows)
        return super().do_GET()

    def do_POST(self):
        if self.path == "/api/open-explorer":
            import os
            n = int(self.headers.get("Content-Length", 0))
            try:
                data = json.loads(self.rfile.read(n) or b"{}")
            except json.JSONDecodeError:
                return self._json({"error": "bad json"}, 400)
            path = (data.get("path") or "").strip()
            if not path or not path.lower().startswith(r"\\192.168.0.98\tank"):
                return self._json({"error": "path outside NAS root not allowed"}, 400)
            if not os.path.exists(path):
                return self._json({"error": "path not found"}, 404)
            try:
                os.startfile(path if os.path.isdir(path) else os.path.dirname(path))
                return self._json({"ok": True})
            except OSError as ex:
                return self._json({"error": str(ex)}, 500)
        if self.path == "/api/systems/update":
            n = int(self.headers.get("Content-Length", 0))
            try:
                data = json.loads(self.rfile.read(n) or b"{}")
            except json.JSONDecodeError:
                return self._json({"error": "bad json"}, 400)
            sid = data.get("id")
            if not sid:
                return self._json({"error": "missing id"}, 400)
            fields = {k: data[k] for k in ("remark", "status") if k in data}
            if not fields:
                return self._json({"error": "nothing to update"}, 400)
            over_file = ROOT / "data" / "structured" / "pc_remark_overrides.json"
            over = json.loads(over_file.read_text(encoding="utf-8")) if over_file.exists() else {}
            over.setdefault(sid, {}).update(fields)
            over_file.write_text(json.dumps(over, ensure_ascii=False, indent=1), encoding="utf-8")
            con = pcsystem.connect()
            sets = ", ".join(f"{k}=?" for k in fields)
            con.execute(f"UPDATE systems SET {sets} WHERE id=?", (*fields.values(), sid))
            con.commit()
            row = dict(con.execute("SELECT id, remark, status FROM systems WHERE id=?", (sid,)).fetchone())
            con.close()
            return self._json({"ok": True, "system": row})
        if self.path != "/api/tickets/update":
            return self._json({"error": "not found"}, 404)
        n = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return self._json({"error": "bad json"}, 400)
        tid = data.get("id")
        if not tid or not re.fullmatch(r"PCT-\d{4}", tid):
            return self._json({"error": "invalid ticket id"}, 400)
        fields = {k: data[k] for k in ("refs", "picked_by", "status", "raised_by", "fix") if k in data}
        if not fields:
            return self._json({"error": "nothing to update"}, 400)
        # persist override (survives daily rebuilds)
        over = json.loads(OVERRIDES.read_text(encoding="utf-8")) if OVERRIDES.exists() else {}
        over.setdefault(tid, {}).update(fields)
        OVERRIDES.write_text(json.dumps(over, ensure_ascii=False, indent=1), encoding="utf-8")
        # apply to live db
        con = pcsystem.connect()
        sets = ", ".join(f"{k}=?" for k in fields)
        con.execute(f"UPDATE tickets SET {sets} WHERE id=?", (*fields.values(), tid))
        con.commit()
        row = dict(con.execute("SELECT * FROM tickets WHERE id=?", (tid,)).fetchone())
        con.close()
        return self._json({"ok": True, "ticket": row})


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("0.0.0.0", 8765), Handler)
    print("serving dashboard + ticket API on http://localhost:8765 (Ctrl+C to stop)")
    srv.serve_forever()
