from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def _body(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length > 1024 * 1024:
            return b""
        return self.rfile.read(length) if length else b""

    def _respond(self) -> None:
        body = self._body()
        payload = json.dumps(
            {
                "ok": True,
                "method": self.command,
                "path": self.path,
                "body_length": len(body),
            },
            separators=(",", ":"),
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        self._respond()

    def do_POST(self) -> None:
        self._respond()

    def log_message(self, format_string: str, *args) -> None:
        return None


def main() -> None:
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()


if __name__ == "__main__":
    main()
