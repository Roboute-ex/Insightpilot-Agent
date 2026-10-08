"""Verify exact source members and restore in a fresh independent environment."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import stat
import subprocess
import venv
import zipfile

MAX_SNAPSHOT_BYTES = 128 * 1024 * 1024


def verify_snapshot(snapshot: Path) -> dict:
    """Read only; reject unlisted members, duplicates, traversal and bad hashes."""
    digest = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    checksum = snapshot.with_suffix(".sha256")
    if checksum.exists():
        expected = checksum.read_text(encoding="utf-8").split()[0]
        if expected != digest:
            raise ValueError("ZIP 整包 SHA256 校验失败。")
    with zipfile.ZipFile(snapshot) as archive:
        entries = archive.infolist()
        names = [entry.filename for entry in entries]
        if len(names) != len({name.casefold() for name in names}):
            raise ValueError("ZIP 存在重复或大小写冲突路径。")
        if sum(entry.file_size for entry in entries) > MAX_SNAPSHOT_BYTES:
            raise ValueError("源码快照展开大小超出 128MiB 安全上限。")
        for entry in entries:
            name = entry.orig_filename  # ZipInfo normalizes Windows separators on read.
            path = PurePosixPath(name)
            if ("\\" in name or path.is_absolute() or PureWindowsPath(name).drive
                    or any(part in {"", ".", ".."} for part in name.split("/"))
                    or stat.S_ISLNK(entry.external_attr >> 16)):
                raise ValueError("ZIP 包含不安全路径或符号链接。")
        manifest = json.loads(archive.read("SHA256SUMS.json"))
        files = manifest.get("files")
        if manifest.get("project_version") != "0.1.0" or not isinstance(files, list) or manifest.get("file_count") != len(files):
            raise ValueError("源码清单版本或数量不一致。")
        expected_names = {"SHA256SUMS.json", "恢复说明.md"}
        for item in files:
            if not isinstance(item, dict) or set(item) != {"path", "size", "sha256"}:
                raise ValueError("源码清单记录不合法。")
            name = "insightpilot-agent/" + item["path"]
            if name in expected_names:
                raise ValueError("源码清单存在重复文件。")
            expected_names.add(name)
            if type(item["size"]) is not int or item["size"] < 0:
                raise ValueError("源码文件大小不合法。")
            raw = archive.read(name)
            if len(raw) != item["size"] or hashlib.sha256(raw).hexdigest() != item["sha256"]:
                raise ValueError("源码哈希不匹配：" + item["path"])
        if set(names) != expected_names:
            raise ValueError("ZIP 包含未在 SHA256 清单中列出的文件，或缺少必需成员。")
    return {"manifest": manifest, "sha256": digest, "outer_checksum_verified": checksum.exists(), "member_count": len(names)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--wheelhouse", type=Path, action="append", default=[])
    args = parser.parse_args()
    folder = args.work_dir.resolve()
    if folder.exists():
        raise SystemExit("恢复目标已存在，拒绝覆盖。")
    verified = verify_snapshot(args.snapshot.resolve())
    manifest = verified["manifest"]
    folder.mkdir(parents=True)
    with zipfile.ZipFile(args.snapshot) as archive:
        archive.extractall(folder)
    project = folder / "insightpilot-agent"
    venv.EnvBuilder(with_pip=True).create(folder / "venv")
    python = folder / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    env = dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    flags = ["--no-index"] if args.wheelhouse else []
    for wheelhouse in args.wheelhouse:
        flags.extend(["--find-links", str(wheelhouse.resolve())])
    records = []

    def run(name, arguments, cwd=folder):
        command = [str(python), "-X", "utf8", *arguments]
        completed = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=1800)
        (folder / (name + ".stdout.txt")).write_text(completed.stdout, encoding="utf-8")
        (folder / (name + ".stderr.txt")).write_text(completed.stderr, encoding="utf-8")
        record = {"name": name, "command": command, "exit_code": completed.returncode}
        records.append(record)
        result = {"snapshot": str(args.snapshot.resolve()), "snapshot_sha256": verified["sha256"],
            "outer_checksum_verified": verified["outer_checksum_verified"],
            "file_count": manifest["file_count"], "member_count": verified["member_count"],
            "python": str(python), "checks": records}
        (folder / "validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(record, ensure_ascii=False), flush=True)
        return completed.returncode

    if run("install_build", ["-m", "pip", "install", "setuptools", "wheel", *flags]):
        return 1
    if (project / "requirements-lock.txt").exists():
        if run("install_locked", ["-m", "pip", "install", "-r", str(project / "requirements-lock.txt"), *flags]):
            return 1
    if run("install_source", ["-m", "pip", "install", "--no-build-isolation", "-e", str(project) + "[app,test]", *flags]):
        return 1
    code = "import insightpilot,importlib.resources as r; assert insightpilot.__version__=='0.1.0'; print(insightpilot.__file__); assert r.files('insightpilot.semantic').joinpath('models/commerce.yaml').is_file()"
    run("outside_import", ["-I", "-c", code])
    run("full_verification", [str(project / "scripts/verify_project.py"), "--output-dir", str(folder / "verification")], cwd=project)
    return int(any(record["exit_code"] for record in records))


if __name__ == "__main__":
    raise SystemExit(main())
