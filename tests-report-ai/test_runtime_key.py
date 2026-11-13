import contextlib
import importlib.util
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("prepare_key", Path(__file__).parents[1] / "tools/server-update/prepare-report-ai-key.py")
prepare_key = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare_key)


class RuntimeKeyTest(unittest.TestCase):
    def run_setup(self, root, encrypted="0", configured=""):
        runtime = root / "etc/carbon-report/llm-encryption.key"
        incoming = root / "runtime-key.input"
        def local_path(value):
            return runtime if str(value) == "/etc/carbon-report/llm-encryption.key" else Path(value)
        with patch.object(prepare_key, "Path", side_effect=local_path), patch.object(prepare_key.sys, "argv", ["prepare", str(incoming)]), patch.dict(os.environ, {"HAS_ENCRYPTED_LLM_KEY": encrypted, "CARBON_REPORT_LLM_CONFIG_ENCRYPTION_KEY": configured}), contextlib.redirect_stdout(io.StringIO()) as output:
            prepare_key.main()
        return runtime, output.getvalue()

    def test_key_is_generated_once_and_never_printed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runtime, output = self.run_setup(root)
            original = runtime.read_text()
            self.assertTrue(original.strip())
            self.assertNotIn(original.strip(), output)
            self.run_setup(root, encrypted="1")
            self.assertEqual(original, runtime.read_text())

    def test_existing_encrypted_data_without_key_stops(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(SystemExit):
                self.run_setup(Path(temp), encrypted="1")
            self.assertFalse((Path(temp) / "etc").exists())

    def test_original_key_is_restored_and_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "runtime-key.input").write_text("original-key\n")
            runtime, _ = self.run_setup(root, encrypted="1")
            self.assertEqual("original-key", runtime.read_text().strip())
            with self.assertRaises(SystemExit):
                self.run_setup(root, encrypted="1", configured="different-key")
            self.assertEqual("original-key", runtime.read_text().strip())


if __name__ == "__main__":
    unittest.main()
