"""Fresh-process explicit exploration costs, separate from static navigation timings."""
from __future__ import annotations
import argparse
from collections import Counter
import functools,importlib.metadata as md,json,os,statistics,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]


def child(args):
    sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/"tests"));os.environ["INSIGHTPILOT_UI_SYNC"]="1"
    from benchmark_performance import MemorySample
    from streamlit.testing.v1 import AppTest
    from pytest import MonkeyPatch
    from ui_expander_support import install_expander_events
    import insightpilot.agents.workflow as workflow
    import insightpilot.agents.dataset as dataset
    import app.components.data_source_panel as source
    import app.components.export_panel as exports
    import app.background_tasks as tasks
    import insightpilot.analysis.exploration as exploration
    from insightpilot.tools.duckdb_engine import AnalyticsEngine
    monkeypatch=MonkeyPatch();install_expander_events(monkeypatch)
    counts=Counter();phase_calls={};stages={};wrappers={};input_ids=set()
    for module,name in [(source,"load_synthetic_tables"),(dataset,"infer_schema_mapping"),(dataset,"fingerprint_dataframe"),
        (workflow,"run_agent_analysis"),(workflow,"_run_playbook_node"),(exploration,"execute_exploration"),
        (AnalyticsEngine,"run_parameterized_sql"),(tasks,"request_work"),(exports,"prepare_export_payload")]:
        original=getattr(module,name)
        @functools.wraps(original)
        def wrapped(*a,_fn=original,_name=name,**kw):
            counts[_name]+=1
            if _name=="fingerprint_dataframe":counts["fingerprint_source" if not input_ids or id(a[0]) in input_ids else "fingerprint_result"]+=1
            return _fn(*a,**kw)
        wrappers[original]=wrapped;monkeypatch.setattr(module,name,wrapped)
    for module in list(sys.modules.values()):
        if module is None or not getattr(module,"__name__","").startswith(("insightpilot.","app.")):continue
        for name,value in list(vars(module).items()):
            try:replacement=wrappers.get(value)
            except TypeError:continue
            if replacement is not None:monkeypatch.setattr(module,name,replacement)
    with MemorySample() as memory:
        app=AppTest.from_file(str(ROOT/"app/ui_streamlit.py"),default_timeout=180)
        app.session_state["demo_scale"]="standard";app.session_state["demo_seed"]=42;app.session_state["data_source_selector"]="synthetic"
        def measure(name,fn):
            before=counts.copy();memory.phase=name;start=time.perf_counter();fn()
            stages[name]=time.perf_counter()-start;phase_calls[name]=dict(counts-before)
            assert not app.exception,[x.message for x in app.exception]
        measure("initial_data_ready",app.run)
        snapshot=app.session_state["performance_dataset"].current;input_ids.update(id(frame) for frame in snapshot.tables.values())
        measure("exploration_navigation",lambda:app.segmented_control(key="workbench_page").set_value("explore").run())
        measure("configure_view",lambda:app.segmented_control(key="exploration_section").set_value(args.case).run())
        assert app.selectbox(key="exploration_table").value=="daily_metrics"
        if args.case=="distribution":app.selectbox(key="exploration_field").set_value("orders")
        else:
            app.selectbox(key="exploration_metric").set_value("orders")
            app.selectbox(key="exploration_row").set_value("city")
            if args.case=="pivot":app.selectbox(key="exploration_column").set_value("channel")
        app.checkbox(key="exploration_confirmed").check()
        measure("explicit_exploration_execution",lambda:app.button(key="exploration_generate").click().run())
        result=app.session_state["last_analysis_result"]
        assert result["execution_status"]=="COMPLETED",result.get("errors")
        info=result["analysis_result_package"]["metadata"]["exploration"]
        assert info["scope_row_count"]==36000
        measure("existing_result_chart_page",lambda:(app.session_state.__setitem__("requested_result_tab","可视化诊断"),app.run()))
        control=next(x for x in app.selectbox if x.label=="展示图型")
        target="box" if args.case=="distribution" else "line" if args.case=="grouped" else "grouped_bar"
        measure("existing_result_chart_style",lambda:control.set_value(target).run())
        for name in ("exploration_navigation","configure_view","existing_result_chart_page","existing_result_chart_style"):
            for fn in ["load_synthetic_tables","infer_schema_mapping","fingerprint_source","run_agent_analysis","execute_exploration","run_parameterized_sql","request_work","prepare_export_payload"]:
                assert not phase_calls[name].get(fn),(name,fn,phase_calls[name])
        assert counts["run_agent_analysis"]==1 and counts["prepare_export_payload"]==0
        record={"case":args.case,"seed":42,"scale":"standard","source_table":"daily_metrics","scope_rows":36000,"stages":stages,"phase_calls":phase_calls,
            "total_calls":dict(counts),"input_fingerprints":snapshot.fingerprints,"retained_dataset_bytes":snapshot.estimated_bytes,
            "tables":{name:{"rows":len(df),"columns":len(df.columns)} for name,df in snapshot.tables.items()},
            "run_id":result["run_manifest"]["run_id"],"request":info["request"],"actual_metadata":info,
            "result_rows":{k:len(v) for k,v in result["result_tables"].items()},"packages":{name:md.version(name) for name in ["pandas","duckdb","streamlit","numpy"]}}
    record["memory"]=memory.summary();monkeypatch.undo()
    args.output.write_text(json.dumps(record,ensure_ascii=False,indent=2,default=str)+"\n",encoding="utf-8")
    print(json.dumps({"case":args.case,"seconds":stages["explicit_exploration_execution"],"sql":phase_calls["explicit_exploration_execution"].get("run_parameterized_sql",0)}),flush=True)
    return 0


def main():
    p=argparse.ArgumentParser();p.add_argument("--output-dir",type=Path,required=True);p.add_argument("--repeat",type=int,default=3);p.add_argument("--child",action="store_true");p.add_argument("--case",choices=["distribution","grouped","pivot"]);p.add_argument("--output",type=Path);args=p.parse_args()
    if args.child:return child(args)
    args.output_dir.mkdir(parents=True,exist_ok=False);runs=[]
    for case in ["distribution","grouped","pivot"]:
        for index in range(args.repeat):
            target=(args.output_dir/f"{case}-{index+1}.json").resolve()
            command=[sys.executable,str(Path(__file__).resolve()),"--child","--case",case,"--output",str(target),"--output-dir",str(args.output_dir.resolve())]
            proc=subprocess.run(command,cwd=ROOT,env=dict(os.environ,PYTHONUTF8="1",PYTHONDONTWRITEBYTECODE="1"),capture_output=True,text=True,encoding="utf-8",timeout=600)
            target.with_suffix(".stdout.txt").write_text(proc.stdout,encoding="utf-8");target.with_suffix(".stderr.txt").write_text(proc.stderr,encoding="utf-8")
            print(json.dumps({"case":case,"iteration":index+1,"exit_code":proc.returncode}),flush=True)
            if proc.returncode:return proc.returncode
            runs.append(json.loads(target.read_text(encoding="utf-8")))
    def summary(values):return {"median":statistics.median(values),"min":min(values),"max":max(values)}
    output={"method":"Fresh Python/AppTest per case/repetition, standard seed42 same daily_metrics36000 rows; synchronous UI for comparable attribution (request_work=0), actual browser separately covers background lifecycle. Each explicit form submission executes once. New distribution/grouped/pivot costs are not compared as static navigation.","cases":{}}
    for case in ["distribution","grouped","pivot"]:
        selected=[r for r in runs if r["case"]==case]
        output["cases"][case]={"stages":{name:summary([r["stages"][name] for r in selected]) for name in selected[0]["stages"]},"rss_peak_bytes":summary([r["memory"]["sampled_peak_bytes"] for r in selected]),"phase_calls":[r["phase_calls"] for r in selected],"scope_rows":36000,"request":selected[0]["request"]}
    (args.output_dir/"summary.json").write_text(json.dumps(output,ensure_ascii=False,indent=2)+"\n",encoding="utf-8");return 0

if __name__=="__main__":raise SystemExit(main())
