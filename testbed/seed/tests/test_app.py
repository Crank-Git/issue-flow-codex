import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app  # noqa: E402


def fetch(server, path):
    url = f"http://127.0.0.1:{server.server_port}{path}"
    try:
        with urllib.request.urlopen(url) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.load(error)


class AppTest(unittest.TestCase):
    def setUp(self):
        self.server = HTTPServer(("127.0.0.1", 0), app.Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def test_greets_a_name(self):
        self.assertEqual(app.greeting("Ada"), "Hello, Ada!")

    def test_reports_health(self):
        self.assertEqual(fetch(self.server, "/health"), (200, {"status": "ok"}))

    def test_serves_a_greeting_at_hello(self):
        self.assertEqual(fetch(self.server, "/hello/Ada"), (200, {"message": "Hello, Ada!"}))

    def test_answers_404_for_an_unknown_path(self):
        self.assertEqual(fetch(self.server, "/nope"), (404, {"error": "not found"}))


if __name__ == "__main__":
    unittest.main()
