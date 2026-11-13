"""Exercise the actual Bash preflight against a Docker stub without touching a server."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class DeployPreflightTest(unittest.TestCase):
    def test_preflight_performs_selects_and_checks_without_applying_payload(self):
        bash = Path("C:/Program Files/Git/bin/bash.exe") if os.name == "nt" else Path(shutil.which("bash") or "/bin/bash")
        if not bash.is_file():
            self.skipTest("Bash is unavailable")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            deploy = root / "deploy-report-ai.sh"
            source = Path(__file__).parents[1] / "tools/server-update/deploy-report-ai.sh"
            deploy.write_text(source.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
            (root / "marker.txt").write_bytes(b"preflight")
            (root / "SHA256SUMS").write_text(hashlib.sha256(b"preflight").hexdigest() + "  marker.txt\n", encoding="utf-8", newline="\n")
            commands = root / "docker-calls.log"
            wrapper = '''
docker() {
  printf '%s\\n' "$*" >> "$TASK_COMMAND_LOG"
  case "$1" in
    inspect) echo true ;;
    exec) case "$*" in *"SELECT COUNT"*) echo 0 ;; esac ;;
    *) echo "Unexpected mutation: $*" >&2; return 99 ;;
  esac
}
export -f docker
bash "$1" --check
'''
            environment = dict(os.environ, MYSQL_ROOT_PASSWORD="test-dummy", TASK_COMMAND_LOG=commands.as_posix())
            result = subprocess.run([str(bash), "-c", wrapper, "preflight-test", deploy.as_posix()],
                                    env=environment, capture_output=True, text=True, timeout=30)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("Preflight passed", result.stdout)
            calls = commands.read_text(encoding="utf-8")
            self.assertIn("SELECT COUNT", calls)
            self.assertNotIn("INSERT INTO", calls)
            self.assertNotIn("UPDATE sys_config", calls)
            self.assertNotIn("stop_java", calls)
            self.assertNotIn("prepare-report-ai-key.py", calls)
            self.assertNotIn("sh /usr/local/bin/start-ruoyi-web.sh", calls)


if __name__ == "__main__":
    unittest.main()
