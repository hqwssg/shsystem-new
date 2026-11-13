"""Read a package manifest from stdin and compare installed files without modifying them."""
import hashlib
from pathlib import Path, PurePosixPath
import re
import sys


def verify(manifest, base=Path("/")):
    mappings = {
        "web-main/jar/ruoyi-admin.jar": "home/ruoyi/ruoyi-admin.jar",
        "web-main/html/dist/": "home/ruoyi/projects/ruoyi-ui/",
        "web-main/renderer/carbon_report_agent/": "home/ruoyi/renderer/carbon_report_agent/",
        "scripts/start-web.sh": "usr/local/bin/start-ruoyi-web.sh",
    }
    counts = dict.fromkeys(mappings, 0)
    failures = []
    seen = set()
    for line in manifest.splitlines():
        hashed, name = line.split("  ", 1)
        if (not re.fullmatch(r"[0-9a-f]{64}", hashed)
                or PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts
                or name in seen):
            raise ValueError("Invalid manifest entry")
        seen.add(name)
        for source, destination in mappings.items():
            if name == source or (source.endswith("/") and name.startswith(source)):
                path = base / (destination + name[len(source):])
                counts[source] += 1
                try:
                    digest = hashlib.sha256()
                    with path.open("rb") as stream:
                        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                            digest.update(chunk)
                    if digest.hexdigest() != hashed:
                        failures.append(str(path))
                except OSError:
                    failures.append(str(path))
                break
    if not all(counts.values()):
        raise ValueError("Manifest does not cover all four deployed components")
    if failures:
        raise ValueError("Installed files missing or changed:\n" + "\n".join(failures))
    print(f"PASS {sum(counts.values())} installed files match the AI delivery manifest.")


if __name__ == "__main__":
    verify(sys.stdin.read())
