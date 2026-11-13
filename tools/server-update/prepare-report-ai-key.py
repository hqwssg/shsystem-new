"""Install the runtime encryption key without displaying it or replacing an existing key."""
import os
from pathlib import Path
import secrets
import sys


def main():
    runtime = Path("/etc/carbon-report/llm-encryption.key")
    incoming = Path(sys.argv[1])
    values = []
    for candidate in (runtime, incoming):
        if candidate.is_file():
            value = candidate.read_text(encoding="utf-8").strip()
            if not value:
                raise SystemExit("ERROR: runtime encryption key file is empty; restore the original key.")
            values.append(value)
    configured = os.environ.get("CARBON_REPORT_LLM_CONFIG_ENCRYPTION_KEY", "").strip()
    if configured:
        values.append(configured)
    if len(set(values)) > 1:
        raise SystemExit("ERROR: existing encryption keys do not match; restore the original configuration.")
    if not values and os.environ.get("HAS_ENCRYPTED_LLM_KEY") != "0":
        raise SystemExit("ERROR: encrypted API key exists but its encryption key is unavailable; restore the original runtime key.")
    value = values[0] if values else secrets.token_urlsafe(48)
    runtime.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(runtime.parent, 0o700)
    if not runtime.exists():
        fd = os.open(runtime, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            output.write(value + "\n")
    os.chmod(runtime, 0o600)
    print("Report AI runtime encryption key is ready; value has not been displayed.")


if __name__ == "__main__":
    main()
