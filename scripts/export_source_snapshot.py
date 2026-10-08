"""Create an account-independent, allowlisted source archive without overwriting."""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
import os
import re
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TOP_FILES = {'README.md', 'AGENTS.md', 'pyproject.toml', 'requirements.txt', 'requirements-lock.txt', 'requirements-langgraph.txt', '.gitignore', '.gitattributes', 'MANIFEST.in', 'LICENSE', 'LICENSE.md', 'NOTICE'}
DIRS = {'insightpilot', 'app', 'examples', 'scripts', 'docs', 'tests'}
EXTENSIONS = {'.py', '.md', '.toml', '.yaml', '.yml', '.txt', '.json', '.ps1', '.css', '.html', '.dot'}

def _linked(path: Path) -> bool:
    # Junctions/reparse points must not traverse outside the approved project.
    return path.is_symlink() or bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400)


def source_files(root: Path = ROOT) -> list[Path]:
    root = root.resolve()
    files = []
    forbidden_dirs = {'.git', '.venv', '__pycache__', 'local_data', 'local_backups', 'exports', 'telemetry', 'node_modules', '.pytest_cache', '.tmp_tests'}
    sensitive_name = re.compile(r'(?:^|[_.-])(secrets?|credentials?|passwords?|tokens?|cookies?|private[_-]?key|recovery[_-]?codes?)(?:$|[_.-])', re.I)
    for directory, dirs, names in os.walk(root, topdown=True, followlinks=False):
        parent = Path(directory)
        dirs[:] = [name for name in dirs if name not in forbidden_dirs and not name.startswith('.venv-') and not _linked(parent/name) and (parent/name).resolve().is_relative_to(root)]
        if parent == root:
            dirs[:] = [name for name in dirs if name in DIRS | {'.github', '.streamlit'}]
        for name in names:
            p = parent/name
            if _linked(p) or not p.resolve().is_relative_to(root) or sensitive_name.search(name) or name in {'.env', 'id_rsa', 'id_ed25519'}:
                continue
            rel = p.relative_to(root)
            allowed = rel.as_posix() == 'tests/fixtures/format_recovery.xls' or (len(rel.parts) == 1 and rel.name in TOP_FILES) or (rel.parts[0] in DIRS and p.suffix in EXTENSIONS) or rel.as_posix() == '.streamlit/config.toml' or (rel.parts[:2] == ('.github', 'workflows') and p.suffix in {'.yml', '.yaml'})
            if allowed:
                files.append(p)
    return sorted(files, key=lambda p: p.relative_to(root).as_posix())

def export_snapshot(output_dir: Path, root: Path = ROOT) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    target = output_dir / f'insightpilot-agent-0.1.0-source-{stamp}.zip'
    inventory = []
    with zipfile.ZipFile(target, 'x', zipfile.ZIP_DEFLATED) as archive:
        for path in source_files(root):
            content = path.read_bytes()
            if b"-----BEGIN " in content and re.search(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", content):
                raise ValueError("发现私钥格式，停止快照：" + path.relative_to(root).as_posix())
            if re.search(rb"(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{70,})", content):
                raise ValueError("发现疑似访问凭据，停止快照：" + path.relative_to(root).as_posix())
            name = path.relative_to(root).as_posix()
            inventory.append({'path':name,'size':len(content),'sha256':hashlib.sha256(content).hexdigest()})
            archive.writestr('insightpilot-agent/'+name, content)
        manifest = {'project_version':'0.1.0','file_count':len(inventory),'files':inventory}
        archive.writestr('SHA256SUMS.json', json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
        archive.writestr('恢复说明.md', '# 源码恢复\n\n先核验 SHA256SUMS.json。进入 insightpilot-agent，创建新 .venv，执行 .venv/Scripts/python.exe -m pip install -e ".[app,test]"。运行 python -m insightpilot.cli --scenario transaction --scale small。\n\n安装依赖需要网络或独立 wheelhouse；安装后分析无需网络、账号或 API key。请参阅项目 docs/backup_and_restore.md。快照包含未提交源码，无输入业务数据、报告、环境、凭据和旧 Git。\n')
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_suffix('.sha256').write_text(digest+'  '+target.name+'\n',encoding='utf-8')
    print(json.dumps({'path':str(target),'file_count':len(inventory),'sha256':digest},ensure_ascii=False))
    return target

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description='导出不含私有数据的源码快照。')
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    export_snapshot(args.output_dir)
