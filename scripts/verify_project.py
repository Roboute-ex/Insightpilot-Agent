"""Run reproducible checks and preserve actual commands and exit codes."""
from __future__ import annotations
import argparse
import datetime as dt
import importlib.metadata as md
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument('--output-dir',type=Path,default=ROOT/'reports'/'verification')
    parser.add_argument('--quick',action='store_true')
    args=parser.parse_args()
    stamp=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder=args.output_dir/stamp
    folder.mkdir(parents=True,exist_ok=False)
    env=dict(os.environ,PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1')
    env.pop('PYTHONPATH',None)
    commands=[('dependencies',['-m','pip','check']),('semantic',['-m','insightpilot.semantic.validate'])]
    if not args.quick:
        commands.append(('pytest',['-m','pytest','--junitxml='+str(folder/'pytest.xml')]))
    for suite in ('core','safety','determinism','task'):
        commands.append(('evaluation_'+suite,['-m','insightpilot.evaluation.cli','--suite',suite,'--output-format','json']))
    for scenario in ('transaction','content','live'):
        commands.append(('cli_'+scenario,['-m','insightpilot.cli','--scenario',scenario,'--scale','small','--output-format','json','--export-dir',str(folder/scenario),'--export-format','pdf,markdown,html,excel,manifest,bundle']))
    commands.append(('plan_only',['-m','insightpilot.cli','--scenario','multi_table_commerce','--plan-only','--output-format','json','--export-dir',str(folder/'preview')]))
    records=[]
    for name,arguments in commands:
        command=[sys.executable,*arguments]
        completed=subprocess.run(command,cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=1800)
        (folder/(name+'.stdout.txt')).write_text(completed.stdout,encoding='utf-8')
        (folder/(name+'.stderr.txt')).write_text(completed.stderr,encoding='utf-8')
        record={'name':name,'command':command,'exit_code':completed.returncode}
        records.append(record)
        print(json.dumps(record,ensure_ascii=False),flush=True)
    result={'python':sys.version,'executable':sys.executable,'packages':{d.metadata['Name']:d.version for d in md.distributions()},'checks':records}
    (folder/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return int(any(r['exit_code'] for r in records))

if __name__=='__main__':
    raise SystemExit(main())
