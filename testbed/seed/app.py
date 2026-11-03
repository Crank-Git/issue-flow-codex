"""A small greeting web service. It is the seed project of the issue-flow test beds."""

import json
from http.server import BaseHTTPRequestHandler, HTTPServer

HELLO_PREFIX = "/hello/"


def greeting(name):
    """Return the greeting text for `name`."""
    return f"Hello, {name}!"


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            self.reply(200, {"status": "ok"})
        elif self.path.startswith(HELLO_PREFIX):
            self.reply(200, {"message": greeting(self.path[len(HELLO_PREFIX):])})
        else:
            self.reply(404, {"error": "not found"})

    def reply(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    HTTPServer(("127.0.0.1", 8000), Handler).serve_forever()


if __name__ == "__main__":
    main()
