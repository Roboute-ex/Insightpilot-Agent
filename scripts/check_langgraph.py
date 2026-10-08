"""Validate the real optional backend against the same deterministic rule nodes."""
from __future__ import annotations
import argparse
import importlib.util
import json
from pathlib import Path
import pandas as pd
from insightpilot.agents.workflow import run_agent_analysis
from insightpilot.data.scenarios import generate_scenario


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if importlib.util.find_spec('langgraph') is None:
        raise SystemExit('LangGraph未安装；此检查必须在独立可选环境执行。')
    records=[]
    cases=[('transaction','昨日订单量为什么下降？','metric_diagnosis'),('content','新策略是否提升了内容完播率？','experiment_analysis'),('live','请定位直播体验异常的主要维度。','live_quality')]
    for scenario,question,goal in cases:
        tables=generate_scenario(scenario,scale='small',seed=42).tables
        rule=run_agent_analysis(question,tables,goal_mode=goal)
        graph=run_agent_analysis(question,tables,goal_mode=goal,use_langgraph=True)
        assert graph['workflow_backend']=='langgraph',graph.get('errors')
        assert graph.get('execution_status')=='COMPLETED',graph.get('errors')
        compared=[]
        for key,table in rule.get('result_tables',{}).items():
            if key in {'quality_checks','quality','evidence','recommendations'} or 'run_id' in table.columns: continue
            if key not in graph.get('result_tables',{}): raise AssertionError('LangGraph缺结果表 '+key)
            pd.testing.assert_frame_equal(table,graph['result_tables'][key])
            compared.append(key)
        assert compared
        records.append({'scenario':scenario,'backend':graph['workflow_backend'],'status':graph['execution_status'],'compared_tables':compared})
    preview=run_agent_analysis(cases[0][1],generate_scenario('transaction',scale='small').tables,use_langgraph=True,plan_only=True)
    assert preview['execution_status']=='PREVIEW'
    assert 'executed_queries' in preview['trace']
    assert not preview['trace']['executed_queries']
    records.append({'scenario':'preview','status':preview['execution_status'],'query_count':len(preview['trace']['executed_queries'])})
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps({'passed':True,'checks':records},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(records,ensure_ascii=False))
    return 0

if __name__=='__main__': raise SystemExit(main())
