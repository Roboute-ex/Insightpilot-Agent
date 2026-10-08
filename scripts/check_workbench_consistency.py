"""Compare actual deterministic result/evidence tables in isolated processes."""
from __future__ import annotations
import argparse, json, subprocess, sys, hashlib
from pathlib import Path


def probe(source):
    sys.path.insert(0, str(source.resolve()))
    import pandas as pd
    from insightpilot.agents.workflow import run_agent_analysis
    from insightpilot.data.scenarios import generate_transaction_scenario, generate_content_scenario, generate_live_scenario
    from insightpilot.reports.manifest import fingerprint_dataframe
    outputs = {}
    for name, generator, question, goal in (
        ("transaction", generate_transaction_scenario, "昨日订单量为什么下降？", "metric_diagnosis"),
        ("experiment", generate_content_scenario, "新策略是否提升了内容完播率？", "experiment_analysis"),
        ("live", generate_live_scenario, "卡顿率上升是否影响观看时长和转化？", "live_quality"),
    ):
        data = generator(scale="small", seed=42)
        result = run_agent_analysis(question, data.tables, goal_mode=goal, presentation_mode="deferred")
        outputs[name] = capture(result, fingerprint_dataframe)
    frame=pd.DataFrame([{"unit_id":f"{group}{i}","group":group,"x":i,"outcome":10+3*i+2*(group=="treatment")} for group in ("control","treatment") for i in range(12)])
    result=run_agent_analysis("比较处理组和对照组的调整效果",{"sample":frame},goal_mode="causal_exploration",playbook_id="causal_exploration",column_mapping={"table_name":"sample","treatment_column":"group","outcome_column":"outcome","metric_columns":["outcome"],"covariates":["x"]},playbook_parameters={"treatment_value":"treatment","control_value":"control","covariates":["x"]},presentation_mode="deferred")
    outputs["causal24"]=capture(result,fingerprint_dataframe)
    print(json.dumps(outputs,ensure_ascii=False,allow_nan=False))


def capture(result,fingerprint):
    assert result["execution_status"]=="COMPLETED",result.get("errors")
    frames={}
    for key,frame in result.get("result_tables",{}).items():
        frames[key]={"rows":len(frame),"columns":list(frame.columns),"sha256":fingerprint(frame)}
    package=result["analysis_result_package"]
    numerical={key:package.get(key) for key in ("metric_comparisons","anomalies","funnel_results","dimension_contributions","experiment_results","evidence")}
    return {"execution_status":result["execution_status"],"tables":frames,"structured_evidence":numerical}


def main():
    p=argparse.ArgumentParser();p.add_argument("--before",type=Path);p.add_argument("--after",type=Path);p.add_argument("--output",type=Path);p.add_argument("--probe",type=Path);args=p.parse_args()
    if args.probe:
        probe(args.probe);return
    args.output.mkdir(parents=True,exist_ok=False)
    values={}
    for label,source in (("before",args.before),("after",args.after)):
        run=subprocess.run([sys.executable,str(Path(__file__).resolve()),"--probe",str(source.resolve())],cwd=args.output.resolve(),capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=180)
        (args.output/(label+".stdout.json")).write_text(run.stdout,encoding="utf-8")
        (args.output/(label+".stderr.txt")).write_text(run.stderr,encoding="utf-8")
        if run.returncode:raise RuntimeError(label+" probe failed: "+run.stderr[-3000:])
        values[label]=json.loads(run.stdout)
    results={key:values["before"][key]==values["after"][key] for key in values["before"]}
    (args.output/"comparison.json").write_text(json.dumps({"equal":results,"scope":"exact dataframe schema/index/value SHA256 plus structured statistics and evidence; run timestamps excluded"},indent=2),encoding="utf-8")
    print(json.dumps(results));assert all(results.values()),"Numerical/evidence drift; inspect both recorded outputs"

if __name__=="__main__":main()
