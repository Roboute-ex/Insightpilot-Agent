"""Small archive/inventory checks; these tests never create a venv or install packages."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import stat
import zipfile
import pytest
from scripts.check_distribution import required_package_files
from scripts.export_source_snapshot import source_files
from scripts.restore_and_verify import verify_snapshot


def tiny_snapshot(tmp_path: Path, *, extra=None, path="README.md", bad_hash=False):
    archive_path = tmp_path / "source.zip"
    content = b"test source\n"
    manifest = {"project_version": "0.1.0", "file_count": 1, "files": [{
        "path": path, "size": len(content), "sha256": "0" * 64 if bad_hash else hashlib.sha256(content).hexdigest(),
    }]}
    with zipfile.ZipFile(archive_path, "x") as archive:
        archive.writestr("insightpilot-agent/" + path, content)
        archive.writestr("SHA256SUMS.json", json.dumps(manifest))
        archive.writestr("恢复说明.md", "test")
        if extra is not None:
            member = zipfile.ZipInfo("placeholder")
            member.filename = extra  # Preserve raw attacker spelling on Windows.
            archive.writestr(member, "unexpected")
    return archive_path


def test_package_inventory_includes_new_modules_models_and_pages():
    names = required_package_files()
    required = {"insightpilot/analysis/threads.py", "insightpilot/tools/sql_safety.py",
        "insightpilot/evaluation/task_suite.py", "insightpilot/analysis/quality.py",
        "insightpilot/reports/definitions.py", "insightpilot/semantic/models/commerce.yaml",
        "app/components/history_panel.py", "app/ui_streamlit.py"}
    assert required.issubset(names)
    root = Path(__file__).resolve().parents[1]
    included = {p.relative_to(root).as_posix() for p in source_files(root)}
    assert set(names).issubset(included)
    assert not any("__pycache__" in name for name in names)


def test_source_manifest_and_outer_hash_are_verified(tmp_path):
    archive = tiny_snapshot(tmp_path)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(".sha256").write_text(digest + "  " + archive.name)
    result = verify_snapshot(archive)
    assert result["sha256"] == digest
    assert result["outer_checksum_verified"] is True
    assert result["member_count"] == 3 and result["manifest"]["file_count"] == 1


def test_unlisted_python_member_is_rejected(tmp_path):
    archive = tiny_snapshot(tmp_path, extra="insightpilot-agent/insightpilot/unlisted.py")
    with pytest.raises(ValueError, match="清单"):
        verify_snapshot(archive)


@pytest.mark.parametrize("path", ["../escape.py", "/absolute.py", "C:/outside.py", "insightpilot-agent/../escape.py", "insightpilot-agent\\escape.py"])
def test_unsafe_zip_member_paths_are_rejected(tmp_path, path):
    archive = tiny_snapshot(tmp_path, extra=path)
    with pytest.raises(ValueError, match="不安全"):
        verify_snapshot(archive)


def test_duplicate_zip_names_are_rejected(tmp_path):
    with pytest.warns(UserWarning):
        archive = tiny_snapshot(tmp_path, extra="insightpilot-agent/README.md")
    with pytest.raises(ValueError, match="重复"):
        verify_snapshot(archive)


def test_symlink_entry_is_rejected(tmp_path):
    archive = tiny_snapshot(tmp_path)
    link = zipfile.ZipInfo("insightpilot-agent/linked.py")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(archive, "a") as output:
        output.writestr(link, "../../outside.py")
    with pytest.raises(ValueError, match="符号链接"):
        verify_snapshot(archive)


def test_bad_source_file_hash_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="源码哈希"):
        verify_snapshot(tiny_snapshot(tmp_path, bad_hash=True))


def test_bad_outer_zip_hash_is_rejected(tmp_path):
    archive = tiny_snapshot(tmp_path)
    archive.with_suffix(".sha256").write_text("0" * 64 + "  source.zip")
    with pytest.raises(ValueError, match="整包"):
        verify_snapshot(archive)


def test_archive_uncompressed_budget_is_enforced(tmp_path, monkeypatch):
    import scripts.restore_and_verify as restore
    archive = tiny_snapshot(tmp_path)
    monkeypatch.setattr(restore, "MAX_SNAPSHOT_BYTES", 1)
    with pytest.raises(ValueError, match="上限"):
        restore.verify_snapshot(archive)
