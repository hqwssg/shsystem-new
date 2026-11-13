"""Verify the delivered artifact, including nested Java resources and renderer CLI."""
import hashlib
import io
from pathlib import Path
import sys
import tarfile
import zipfile


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    root = Path(sys.argv[1]).resolve()
    manifest = (root / "SHA256SUMS").read_text(encoding="utf-8")
    expected = {}
    for line in manifest.splitlines():
        hashed, name = line.split("  ", 1)
        path = (root / name).resolve()
        assert path.is_relative_to(root), name
        assert path.is_file() and digest(path) == hashed, name
        expected[name] = hashed
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() and p.name != "SHA256SUMS"}
    assert actual == set(expected), "Manifest coverage mismatch"
    assert not any(p.endswith((".sql", ".key", ".pyc")) or "/__pycache__/" in p or Path(p).name.startswith(".env") for p in actual)
    deploy = (root / "deploy-report-ai.sh").read_text(encoding="utf-8")
    assert "mysqldump" not in deploy and "BACKUP_DIR" not in deploy
    assert "--check" in deploy and "prepare-report-ai-key.py" in deploy
    if "scripts/check-report-ai-health.sh" in expected:
        assert "check-report-ai-health.sh" in deploy and "verify-report-ai-files.py" in deploy
        health = (root / "scripts/check-report-ai-health.sh").read_text(encoding="utf-8")
        assert '/uncertainty/uncertainty-wizard.html" 200' in health
        assert '/uncertainty/" 200' not in health
    assert "test-llm" in (root / "web-main/renderer/carbon_report_agent/cli.py").read_text(encoding="utf-8")
    with zipfile.ZipFile(root / "web-main/jar/ruoyi-admin.jar") as jar:
        name = next(n for n in jar.namelist() if n.startswith("BOOT-INF/lib/ruoyi-modules-carbon-report-") and n.endswith(".jar"))
        with zipfile.ZipFile(io.BytesIO(jar.read(name))) as report:
            assert "com/ruoyi/carbon/report/service/ReportLlmConfigService.class" in report.namelist()
            assert "com/ruoyi/carbon/report/generation/LlmRuntimeConfig.class" in report.namelist()
            assert "mapper/carbon/report/ReportLlmConfigMapper.xml" in report.namelist()
    frontend = root / "web-main/html/dist"
    assert (frontend / "index.html").is_file()
    assert any(b"/llm-config/default" in path.read_bytes() for path in frontend.rglob("*.js")), "AI configuration UI missing"
    archive = root.with_suffix(".tar.gz")
    # Package names contain no suffix, so with_suffix appends the archive suffix.
    expected_archive = Path(str(archive) + ".sha256").read_text(encoding="utf-8").split()[0]
    assert digest(archive) == expected_archive, "Archive SHA256 mismatch"
    with tarfile.open(archive, "r:gz") as tar:
        archived = set()
        for entry in tar:
            parts = Path(entry.name).parts
            assert parts[0] == root.name and ".." not in parts and not entry.issym() and not entry.islnk(), entry.name
            if entry.isfile():
                name = "/".join(parts[1:])
                if name != "SHA256SUMS":
                    assert hashlib.sha256(tar.extractfile(entry).read()).hexdigest() == expected[name], name
                else:
                    assert tar.extractfile(entry).read() == (root / "SHA256SUMS").read_bytes()
                archived.add(name)
        assert archived == actual | {"SHA256SUMS"}, "Archive payload mismatch"
    print(f"PASS: {len(expected)} payload hashes, archive content/hash, Java AI classes/mapper, frontend and Python CLI; no SQL or runtime keys.")


if __name__ == "__main__":
    main()
