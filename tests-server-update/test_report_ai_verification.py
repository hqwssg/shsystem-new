"""Regression checks for the AI deployment false failure and installed-file verification."""
import hashlib
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools/server-update"
spec = importlib.util.spec_from_file_location("verify_files", TOOLS / "verify-report-ai-files.py")
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


class InstalledFilesTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name)
        self.records = []
        files = {
            "web-main/jar/ruoyi-admin.jar": "home/ruoyi/ruoyi-admin.jar",
            "web-main/html/dist/index.html": "home/ruoyi/projects/ruoyi-ui/index.html",
            "web-main/renderer/carbon_report_agent/cli.py": "home/ruoyi/renderer/carbon_report_agent/cli.py",
            "scripts/start-web.sh": "usr/local/bin/start-ruoyi-web.sh",
        }
        for source, installed in files.items():
            path = self.base / installed
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(source.encode())
            self.records.append(hashlib.sha256(path.read_bytes()).hexdigest() + "  " + source)

    def test_matching_delivery_passes(self):
        verifier.verify("\n".join(self.records), self.base)

    def test_partial_copy_is_rejected(self):
        (self.base / "home/ruoyi/projects/ruoyi-ui/index.html").unlink()
        with self.assertRaisesRegex(ValueError, "missing or changed"):
            verifier.verify("\n".join(self.records), self.base)

    def test_wrong_backend_is_rejected(self):
        (self.base / "home/ruoyi/ruoyi-admin.jar").write_bytes(b"old JAR")
        with self.assertRaisesRegex(ValueError, "missing or changed"):
            verifier.verify("\n".join(self.records), self.base)

    def test_incomplete_manifest_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "all four"):
            verifier.verify("\n".join(self.records[:-1]), self.base)

    def test_traversal_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Invalid manifest"):
            verifier.verify("0" * 64 + "  ../outside", self.base)


class HealthProbeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bash = shutil.which("bash")
        if os.name == "nt":
            cls.bash = str(Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git/bin/bash.exe")
        if not cls.bash or not Path(cls.bash).is_file():
            raise unittest.SkipTest("Bash is required")

    def probe(self, failure=""):
        with tempfile.TemporaryDirectory() as folder:
            temp = Path(folder)
            docker = temp / "docker"
            docker.write_text('''#!/bin/bash
if [ "$1" = inspect ]; then echo true; exit 0; fi
if [ "$FAILURE" = runtime ]; then exit 1; fi
echo 'mock runtime check'
''', encoding="utf-8", newline="\n")
            curl = temp / "curl"
            curl.write_text('''#!/bin/bash
url=${!#}
printf '%s\\n' "$url" >> "$REQUEST_LOG"
if [[ "$url" == */uncertainty/ ]]; then echo 500
elif [[ "$url" == *uncertainty-wizard.html && "$FAILURE" == page ]]; then echo 500
elif [[ "$url" == */api/uncertainty/* && "$FAILURE" == api ]]; then echo 500
elif [[ "$url" == */api/uncertainty/* && "$FAILURE" == exposed ]]; then echo 200
elif [[ "$url" == *:53231/* && "$FAILURE" == screen ]]; then echo 502
elif [[ "$url" == */api/uncertainty/* || "$url" == */platform/orgs ]]; then echo 401
else echo 200; fi
''', encoding="utf-8", newline="\n")
            docker.chmod(0o755)
            curl.chmod(0o755)
            env = dict(os.environ, HEALTH_ATTEMPTS="1", FAILURE=failure)
            command = '''mock_dir=$1
if command -v cygpath >/dev/null; then mock_dir=$(cygpath -u "$mock_dir"); fi
export PATH="$mock_dir:$PATH" REQUEST_LOG="$mock_dir/requests.txt"
bash "$2"
'''
            result = subprocess.run([self.bash, "-c", command, "test", temp.as_posix(),
                                     (TOOLS / "check-report-ai-health.sh").as_posix()],
                                    env=env, capture_output=True, text=True, timeout=20)
            requests = (temp / "requests.txt").read_text() if (temp / "requests.txt").exists() else ""
            return result, requests

    def test_real_page_passes_without_probing_unmapped_root(self):
        result, requests = self.probe()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("/uncertainty/uncertainty-wizard.html", requests)
        self.assertNotIn("http://127.0.0.1:53221/uncertainty/\n", requests)

    def test_real_failures_and_missing_authorization_are_rejected(self):
        for failure in ("page", "api", "exposed", "screen", "runtime"):
            with self.subTest(failure=failure):
                result, _ = self.probe(failure)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
