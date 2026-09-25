import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from scripts import update_dynv6


class Response:
    def __init__(self, body=b"addresses updated"):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, _limit):
        return self.body


class Dynv6UpdateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.config = patch.object(update_dynv6, "CONFIG_DIR", Path(self.directory.name))
        self.config.start()
        self.addCleanup(self.config.stop)
        (update_dynv6.CONFIG_DIR / "dynv6.zone").write_text("biblioteca.dns.army")
        (update_dynv6.CONFIG_DIR / "dynv6.token").write_text("test-secret-token")

    def test_timeout_is_retried_without_leaking_token(self):
        output = io.StringIO()
        with patch.object(update_dynv6, "urlopen", side_effect=[TimeoutError(), Response()]) as request, \
             patch.object(update_dynv6.time, "sleep"), contextlib.redirect_stdout(output):
            self.assertEqual(update_dynv6.main("8.8.8.8"), 0)
        self.assertEqual(request.call_count, 2)
        url = request.call_args.args[0].full_url
        self.assertIn("https://dynv6.com/api/update?", url)
        self.assertIn("ipv4=8.8.8.8", url)
        self.assertNotIn("test-secret-token", output.getvalue())

    def test_scheduled_run_discovers_current_ipv4(self):
        with patch.object(update_dynv6, "urlopen", side_effect=[Response(b"8.8.8.8"), Response()]) as request:
            self.assertEqual(update_dynv6.main(), 0)
        self.assertEqual(request.call_count, 2)
        self.assertIn("ipv4=8.8.8.8", request.call_args.args[0].full_url)

    def test_repeated_timeout_is_temporary_failure(self):
        errors = io.StringIO()
        with patch.object(update_dynv6, "urlopen", side_effect=TimeoutError()), \
             patch.object(update_dynv6.time, "sleep") as sleep, contextlib.redirect_stderr(errors):
            self.assertEqual(update_dynv6.main("8.8.8.8"), 1)
        self.assertEqual(sleep.call_count, 2)
        self.assertIn("volverá a probar", errors.getvalue())
        self.assertNotIn("test-secret-token", errors.getvalue())

    def test_invalid_token_is_permanent_failure(self):
        errors = io.StringIO()
        rejection = HTTPError("https://dynv6.com/api/update", 401, "Unauthorized", None, None)
        with patch.object(update_dynv6, "urlopen", side_effect=rejection) as request, \
             patch.object(update_dynv6.time, "sleep") as sleep, contextlib.redirect_stderr(errors):
            self.assertEqual(update_dynv6.main("8.8.8.8"), 2)
        self.assertEqual(request.call_count, 1)
        sleep.assert_not_called()
        self.assertIn("rechazó", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
