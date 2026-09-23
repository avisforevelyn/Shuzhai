#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Shuzhai (书斋) · self-hosted server
Serves the single-page frontend from ./static and the vault API under /api/vault.
Zero dependencies: Python 3.9+ standard library only (sqlite3 included).

Environment:
  SHUZHAI_HOST   bind address            default 127.0.0.1 (put nginx/caddy in front for HTTPS)
  SHUZHAI_PORT   port                    default 8790
  SHUZHAI_DATA   data directory          default ./data   (vault.db lives here)
  SHUZHAI_USER / SHUZHAI_PASS
                 HTTP Basic auth         both set = the whole site requires login; unset = open (LAN use only!)
  SHUZHAI_MAX_MB max upload size in MB   default 64
"""
import os, sys, json, base64, hmac, mimetypes
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault("SHUZHAI_DATA", os.path.join(HERE, "data"))
import vault_api  # noqa: E402  (initialises the SQLite schema on import)

STATIC = os.path.join(HERE, "static")
HOST = os.environ.get("SHUZHAI_HOST", "127.0.0.1")
PORT = int(os.environ.get("SHUZHAI_PORT", "8790"))
USER = os.environ.get("SHUZHAI_USER") or ""
PASS = os.environ.get("SHUZHAI_PASS") or ""
MAX_BODY = int(float(os.environ.get("SHUZHAI_MAX_MB", "64")) * 1024 * 1024)
AUTH_ON = bool(USER and PASS)

mimetypes.add_type("application/manifest+json", ".json")


class H(BaseHTTPRequestHandler):
    server_version = "Shuzhai/1.0"
    protocol_version = "HTTP/1.1"

    # ---- helpers the vault module expects ----
    def _cors(self):
        pass  # same-origin only; nothing to add

    def _json(self, obj, status=200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        sys.stdout.write("%s - %s\n" % (self.address_string(), fmt % args)); sys.stdout.flush()

    # ---- auth ----
    def _authed(self):
        if not AUTH_ON:
            return True
        h = self.headers.get("Authorization", "")
        if h.startswith("Basic "):
            try:
                u, _, p = base64.b64decode(h[6:].strip()).decode("utf-8", "replace").partition(":")
                if hmac.compare_digest(u, USER) and hmac.compare_digest(p, PASS):
                    return True
            except Exception:
                pass
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="Shuzhai", charset="UTF-8"')
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", "12")
        self.end_headers()
        self.wfile.write(b"Unauthorized")
        return False

    # ---- body ----
    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            self._json({"ok": False, "error": "body too large (limit %d MB)" % (MAX_BODY // 1048576)}, 413)
            return None
        return self.rfile.read(n) if n else b""

    # ---- static ----
    def _static(self, path):
        rel = path.lstrip("/") or "index.html"
        full = os.path.normpath(os.path.join(STATIC, rel))
        if not full.startswith(STATIC + os.sep) and full != STATIC:
            self._json({"ok": False, "error": "not found"}, 404); return
        if os.path.isdir(full):
            full = os.path.join(full, "index.html")
        if not os.path.isfile(full):
            self._json({"ok": False, "error": "not found"}, 404); return
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith("json") or ctype.endswith("javascript"):
            ctype += "; charset=utf-8"
        with open(full, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache" if full.endswith((".html", ".json")) else "public, max-age=86400")
        self.end_headers()
        self.wfile.write(data)

    # ---- verbs ----
    def do_GET(self):
        if not self._authed():
            return
        p = urlparse(self.path)
        if p.path == "/api/health":
            return self._json({"ok": True, "app": "shuzhai", "auth": AUTH_ON})
        if p.path.startswith("/api/vault"):
            return vault_api.route_get(self, p, parse_qs(p.query))
        if p.path.startswith("/api/"):
            return self._json({"ok": False, "error": "unknown route"}, 404)
        return self._static(p.path)

    def do_POST(self):
        if not self._authed():
            return
        p = urlparse(self.path)
        raw = self._body()
        if raw is None:
            return
        if p.path.startswith("/api/vault/upload_bin"):
            return vault_api.route_post_bin(self, p, raw)
        if p.path.startswith("/api/vault"):
            try:
                body = json.loads(raw) if raw else {}
            except Exception as e:
                return self._json({"ok": False, "error": "bad json: " + str(e)[:120]}, 400)
            return vault_api.route_post(self, p, body)
        return self._json({"ok": False, "error": "unknown route"}, 404)

    def do_DELETE(self):
        if not self._authed():
            return
        p = urlparse(self.path)
        if p.path.startswith("/api/vault"):
            return vault_api.route_delete(self, p)
        return self._json({"ok": False, "error": "unknown route"}, 404)


def main():
    srv = ThreadingHTTPServer((HOST, PORT), H)
    srv.daemon_threads = True
    print("Shuzhai listening on http://%s:%d  (data: %s, auth: %s)" % (
        HOST, PORT, vault_api.DB_PATH, "on" if AUTH_ON else "OFF - set SHUZHAI_USER/SHUZHAI_PASS before exposing this"))
    sys.stdout.flush()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
