import io
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import subprocess
import sys
import threading
import unittest
import urllib.error
from unittest.mock import patch

from carbon_report_agent.llm_narrative import check_llm_connection


class LlmConnectionTest(unittest.TestCase):
    def test_cli_command_reaches_mock_model_end_to_end(self):
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                self.server.request_model = request["model"]
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"choices":[{"message":{"content":"OK"}}]}')
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            environment = dict(os.environ, CARBON_REPORT_LLM_BASE_URL=f"http://127.0.0.1:{server.server_port}",
                               CARBON_REPORT_LLM_MODEL="mock-model", CARBON_REPORT_LLM_API_KEY="test-key")
            result = subprocess.run([sys.executable, "-m", "carbon_report_agent.cli", "test-llm"],
                                    env=environment, capture_output=True, text=True, timeout=30)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertTrue(json.loads(result.stdout)["ok"])
            self.assertEqual("mock-model", server.request_model)
            self.assertNotIn("test-key", result.stdout + result.stderr)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_same_endpoint_model_and_env_key_as_generation(self):
        response = io.BytesIO(json.dumps({"choices": [{"message": {"content": "OK"}}]}).encode())
        with patch.dict(os.environ, {"CARBON_REPORT_LLM_API_KEY": "test-key", "CARBON_REPORT_LLM_BASE_URL": "https://example.com/v1", "CARBON_REPORT_LLM_MODEL": "test-model"}), patch("urllib.request.urlopen", return_value=response) as send:
            check_llm_connection()
        request = send.call_args.args[0]
        self.assertEqual("https://example.com/v1/chat/completions", request.full_url)
        self.assertEqual("test-model", json.loads(request.data)["model"])
        self.assertEqual("Bearer test-key", request.get_header("Authorization"))
        self.assertEqual(20, send.call_args.kwargs["timeout"])

    def test_http_failure_hides_remote_body_and_key(self):
        error = urllib.error.HTTPError("https://example.com", 401, "secret-test-key", {}, io.BytesIO(b"secret-test-key"))
        with patch.dict(os.environ, {"CARBON_REPORT_LLM_API_KEY": "secret-test-key"}), patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaisesRegex(ValueError, "HTTP 401") as caught:
                check_llm_connection()
        self.assertNotIn("secret-test-key", str(caught.exception))

    def test_missing_key_does_not_send_request(self):
        with patch.dict(os.environ, {"CARBON_REPORT_LLM_API_KEY": "", "OPENAI_API_KEY": ""}), patch("urllib.request.urlopen") as send:
            with self.assertRaisesRegex(ValueError, "API Key"):
                check_llm_connection()
            send.assert_not_called()

    def test_invalid_response_is_rejected(self):
        with patch.dict(os.environ, {"CARBON_REPORT_LLM_API_KEY": "test-key"}), patch("urllib.request.urlopen", return_value=io.BytesIO(b'{"choices":[]}')):
            with self.assertRaises(ValueError):
                check_llm_connection()


if __name__ == "__main__":
    unittest.main()
