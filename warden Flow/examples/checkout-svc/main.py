"""checkout-svc — a tiny stdlib HTTP service, deployable as-is.

No third-party dependencies: it is here so the DELIVER workflow has a real,
self-contained repository to assess and containerize.
"""

from __future__ import annotations

import http.server
import os
import sys
from urllib.parse import urlparse

VERSION = "1.4.2"


def main() -> None:
    endpoint = os.environ.get("PAYMENT_ENDPOINT", "")
    if urlparse(endpoint).scheme not in ("http", "https"):
        print(f"FATAL: unsupported URL scheme in PAYMENT_ENDPOINT: {endpoint!r}")
        sys.exit(1)

    port = int(os.environ.get("PORT", "8080"))

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = b'{"status":"ok","version":"1.4.2"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args) -> None:  # keep the logs quiet
            pass

    print(f"checkout-svc {VERSION} listening on :{port}")
    http.server.HTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
