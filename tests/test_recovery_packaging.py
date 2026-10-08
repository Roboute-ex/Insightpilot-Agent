from __future__ import annotations
import hashlib
import importlib.resources as resources
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]

def test_package_data_and_versions():
    import tomllib
    from insightpilot import __version__
    assert tomllib.loads((ROOT/'pyproject.toml').read_text(encoding='utf-8'))['project']['version'] == __version__ == '0.1.0'
    assert resources.files('insightpilot.semantic').joinpath('models/commerce.yaml').read_text(encoding='utf-8')
    from insightpilot.reports.pdf import generate_pdf_report
    from insightpilot.data.scenarios import generate_scenario
    from insightpilot.data.example_questions import get_example_questions
    assert callable(generate_pdf_report) and callable(generate_scenario) and callable(get_example_questions)

def test_ignore_rules_keep_restored_source(tmp_path):
    repo=tmp_path/'ignore-check'; repo.mkdir()
    shutil.copy2(ROOT/'.gitignore',repo/'.gitignore')
    subprocess.run(['git','init','--quiet',str(repo)],check=True)
    sources=['insightpilot/reports/pdf.py','insightpilot/data/scenarios/transaction.py','insightpilot/data/example_questions.py','insightpilot/semantic/models/commerce.yaml','.streamlit/config.toml']
    for name in sources:
        r=subprocess.run(['git','-C',str(repo),'check-ignore','--no-index',name],capture_output=True)
        assert r.returncode==1,(name,r.stdout)
    for name in ['reports/demo.pdf','.venv/pyvenv.cfg','.env','.streamlit/secrets.toml','local_data/private.csv']:
        r=subprocess.run(['git','-C',str(repo),'check-ignore','--no-index',name],capture_output=True)
        assert r.returncode==0,name

def test_snapshot_whitelist_and_hashes(tmp_path):
    from scripts.export_source_snapshot import export_snapshot
    archive=export_snapshot(tmp_path)
    with zipfile.ZipFile(archive) as z:
        manifest=json.loads(z.read('SHA256SUMS.json'))
        assert manifest['file_count']>220
        names=z.namelist()
        assert 'insightpilot-agent/insightpilot/reports/pdf.py' in names
        assert 'insightpilot-agent/.streamlit/config.toml' in names
        for row in manifest['files']:
            assert hashlib.sha256(z.read('insightpilot-agent/'+row['path'])).hexdigest()==row['sha256']
        assert not any('/.venv/' in n or '/.git/' in n or n.endswith('/secrets.toml') for n in names)
        assert not any(n.startswith('insightpilot-agent/reports/') for n in names)


def test_snapshot_excludes_nested_environments_and_secret_names(tmp_path):
    from scripts.export_source_snapshot import source_files
    for name in ['insightpilot/reports/pdf.py', 'insightpilot/reports/.venv/leak.py', 'docs/credentials.json', 'tests/secrets.txt', '.streamlit/secrets.toml', 'tests/fixtures/format_recovery.xls']:
        path=tmp_path/name; path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(b'synthetic')
    names={p.relative_to(tmp_path).as_posix() for p in source_files(tmp_path)}
    assert names=={'insightpilot/reports/pdf.py','tests/fixtures/format_recovery.xls'}
