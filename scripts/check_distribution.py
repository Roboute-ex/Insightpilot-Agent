"""Verify an exact wheel in a new venv, outside the working source checkout."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import venv
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_EXTENSIONS = {".py", ".yaml", ".yml", ".css", ".html", ".js", ".svg", ".png", ".ttf", ".otf"}


def required_package_files(root: Path = ROOT) -> list[str]:
    # Compare every module/model/page asset, including newly added capabilities.
    return sorted(path.relative_to(root).as_posix() for name in ("insightpilot", "app")
        for path in (root / name).rglob("*") if path.is_file()
        and "__pycache__" not in path.parts and path.suffix in PACKAGE_EXTENSIONS)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheel", type=Path, help="Exact newly built wheel; avoids selecting an older same-version artifact.")
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--wheelhouse", type=Path, action="append", default=[])
    parser.add_argument("--dependency-mode", choices=("locked", "project"), default="locked",
        help="locked: restore local locked versions; project: resolve wheel dependencies for this Python/platform.")
    args = parser.parse_args()
    wheels = sorted((ROOT / "dist").glob("*.whl"))
    wheel = args.wheel.resolve() if args.wheel else (wheels[-1].resolve() if wheels else None)
    if wheel is None or not wheel.is_file():
        raise SystemExit("请先在新的输出目录构建 wheel，并通过 --wheel 指定。")
    required = required_package_files()
    with zipfile.ZipFile(wheel) as archive:
        members = archive.namelist()
        if len(members) != len(set(members)):
            raise SystemExit("wheel 包含重复成员。")
        missing = set(required) - set(members)
        if missing:
            raise SystemExit("wheel 缺少源码模块或页面资产：" + str(sorted(missing)))
    folder = args.work_dir.resolve() if args.work_dir else Path(tempfile.mkdtemp(prefix="insightpilot-wheel-"))
    folder.mkdir(parents=True, exist_ok=True)
    envdir = folder / "venv"
    if envdir.exists() or (folder / "validation.json").exists():
        raise SystemExit("拒绝覆盖已经存在的验证环境或结果。")
    venv.EnvBuilder(with_pip=True).create(envdir)
    python = envdir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    env = dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    flags = ["--no-index"] if args.wheelhouse else []
    for wheelhouse in args.wheelhouse:
        flags.extend(["--find-links", str(wheelhouse.resolve())])
    records = []
    result = {"wheel": str(wheel), "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
        "required_files": required, "required_file_count": len(required), "python": str(python),
        "dependency_mode": args.dependency_mode, "checks": records}

    def run(name, arguments):
        command = [str(python), "-X", "utf8", *arguments]
        completed = subprocess.run(command, cwd=folder, env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=1800)
        (folder / (name + ".stdout.txt")).write_text(completed.stdout, encoding="utf-8")
        (folder / (name + ".stderr.txt")).write_text(completed.stderr, encoding="utf-8")
        record = {"name": name, "command": command, "exit_code": completed.returncode}
        records.append(record)
        (folder / "validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(record, ensure_ascii=False), flush=True)
        return completed.returncode

    lock = ROOT / "requirements-lock.txt"
    if args.dependency_mode == "locked" and lock.exists() and run("install_locked", ["-m", "pip", "install", "-r", str(lock), *flags]):
        return 1
    if run("install_wheel", ["-m", "pip", "install", str(wheel), *flags]):
        return 1
    code = """import insightpilot, importlib.resources as r, json
from insightpilot.data.example_questions import get_example_questions
from insightpilot.tools.sql_safety import SQL_POLICY_VERSION
import app.components.history_panel, app.components.export_panel
assert insightpilot.__version__ == '0.1.0'
assert 'site-packages' in str(insightpilot.__file__)
assert r.files('insightpilot.semantic').joinpath('models/commerce.yaml').is_file()
assert len(get_example_questions()) == 39
print(json.dumps({'version': insightpilot.__version__, 'file': insightpilot.__file__, 'sql_policy_version': SQL_POLICY_VERSION}))
"""
    run("outside_import", ["-I", "-c", code])
    run("dependencies", ["-I", "-m", "pip", "check"])
    run("semantic", ["-I", "-m", "insightpilot.semantic.validate"])
    # Real installed workflows: clarification, SQL scopes, history, experiment,
    # six exports/PDF contents and ZIP binding. No source-tree imports or mocks
    # replace the calculation whose numerical result is under verification.
    run("upstream_task_contracts", ["-I", "-m", "insightpilot.evaluation.cli", "--suite", "task", "--output-format", "json"])
    return int(any(record["exit_code"] for record in records))


if __name__ == "__main__":
    raise SystemExit(main())
