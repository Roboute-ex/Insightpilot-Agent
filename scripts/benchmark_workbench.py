"""Fresh-process UI performance probes: synthetic data only, actual calls, 20ms native RSS.

The before source can be an extracted allowlisted snapshot. Output directories never
replace earlier measurements. Display-only operations are asserted not to compute.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from dataclasses import asdict
import functools, hashlib, importlib.metadata as metadata, json, os, platform
from pathlib import Path
import statistics, subprocess, sys, time
ROOT = Path(__file__).resolve().parents[1]


def child(args):
    source = args.source_root.resolve()
    sys.path.insert(0, str(source))
    sys.path.insert(0, str(source / "tests"))
    os.environ["INSIGHTPILOT_UI_SYNC"] = "1"
    from benchmark_performance import MemorySample
    from streamlit.testing.v1 import AppTest
    from pytest import MonkeyPatch
    from ui_expander_support import install_expander_events
    import insightpilot.agents.workflow as workflow
    import insightpilot.agents.dataset as dataset
    import insightpilot.planning.planner as planner
    import app.components.data_source_panel as data
    import app.components.export_panel as exports
    import app.background_tasks as tasks
    from insightpilot.tools.duckdb_engine import AnalyticsEngine
    from insightpilot.performance import PerformanceConfig
    import insightpilot.ingestion.validation as validation
    import insightpilot.visualization.result_charts as charts
    assert Path(workflow.__file__).resolve().is_relative_to(source)
    monkeypatch = MonkeyPatch()
    install_expander_events(monkeypatch)
    counts = Counter(); timings = defaultdict(float); phase_counts = {}; stages = {}; notes = {}
    input_frame_ids = set()
    hash_records = []
    targets = [(data, "load_synthetic_tables"), (dataset, "infer_schema_mapping"),
               (dataset, "fingerprint_dataframe"), (validation, "validate_dataframe_for_analysis"),
               (workflow, "run_agent_analysis"), (workflow, "_run_routed_analysis"),
               (workflow, "_run_playbook_node"), (planner, "prepare_analysis_request"),
               (exports, "prepare_export_payload"), (tasks, "request_work"),
               (AnalyticsEngine, "run_parameterized_sql"), (charts, "materialize_charts")]
    wrappers = {}
    for module, name in targets:
        original = getattr(module, name)
        @functools.wraps(original)
        def wrapped(*a, _fn=original, _name=name, **kw):
            counts[_name] += 1; start = time.perf_counter()
            if _name == "fingerprint_dataframe" and a:
                label = "fingerprint_source_frame" if id(a[0]) in input_frame_ids or not input_frame_ids else "fingerprint_result_frame"
                counts[label] += 1
                hash_records.append({"kind": label, "rows": len(a[0]), "columns": len(a[0].columns)})
            try: return _fn(*a, **kw)
            finally: timings[_name] += time.perf_counter() - start
        wrappers[original] = wrapped
        monkeypatch.setattr(module, name, wrapped)
    for module in list(sys.modules.values()):
        if module is None or not getattr(module, "__name__", "").startswith(("insightpilot.", "app.")): continue
        for name, value in list(vars(module).items()):
            try: replacement = wrappers.get(value)
            except TypeError: continue
            if replacement is not None: monkeypatch.setattr(module, name, replacement)
    with MemorySample() as memory:
        app = AppTest.from_file(str(source / "app/ui_streamlit.py"), default_timeout=180)
        app.session_state["demo_scale"] = "standard"
        app.session_state["data_source_selector"] = "synthetic"
        def measure(name, fn):
            before = counts.copy(); memory.phase = name; start = time.perf_counter()
            value = fn(); stages[name] = time.perf_counter() - start
            phase_counts[name] = dict(counts-before)
            assert not app.exception, [x.message for x in app.exception]
            return value
        def click(label): next(x for x in app.button if x.label == label).click().run()
        def nav(label): app.session_state["requested_result_tab"] = label; app.run()
        def expand(key, value=True): app.session_state[key] = value; app.run()
        def main_nav(value): app.segmented_control(key="workbench_page").set_value(value).run()
        measure("initial_data_ready", app.run)
        input_frame_ids.update(id(frame) for frame in app.session_state["performance_dataset"].current.tables.values())
        measure("question_advice", lambda: app.text_input(key="question").set_value("昨日订单量为什么下降？").run())
        workbench = any(x.key == "workbench_page" for x in app.segmented_control)
        notes["ui_generation"] = "workbench" if workbench else "guided"
        measure("method_catalog_open", lambda: main_nav("methods") if workbench else expand("guided_all_methods"))
        notes["catalog_configure_buttons"] = [x.label for x in app.button if x.label.startswith("配置：")]
        assert len(notes["catalog_configure_buttons"]) >= 10
        measure("method_catalog_close", lambda: main_nav("workbench") if workbench else expand("guided_all_methods", False))
        if workbench:
            measure("new_exploration_navigation", lambda: main_nav("explore"))
            measure("new_exploration_return", lambda: main_nav("workbench"))
        measure("analysis_first", lambda: click("开始分析"))
        result = app.session_state["last_analysis_result"]
        assert result["execution_status"] == "COMPLETED", result.get("errors")
        first_run = result["run_manifest"]["run_id"]
        measure("analysis_repeat", lambda: click("开始分析"))
        assert app.session_state["last_analysis_result"]["run_manifest"]["run_id"] == first_run
        measure("details_page", lambda: nav("结果明细"))
        choices = [(key, len(frame)) for key, frame in result["result_tables"].items() if len(frame) > 50]
        if choices:
            key, rows = max(choices, key=lambda item: item[1])
            measure("pagination_select_table", lambda: app.selectbox(key="result_table_selector").set_value(key).run())
            measure("pagination_set_50", lambda: next(x for x in app.selectbox if x.label == "每页行数").set_value(50).run())
            measure("pagination_page_two", lambda: next(x for x in app.number_input if x.label == "页码").set_value(2).run())
            notes["paginated_table"] = {"key": key, "rows": rows}
        else: notes["pagination"] = "No full result table above 50 rows; no fabricated pagination measurement."
        measure("chart_page", lambda: nav("可视化诊断"))
        chart_keys = [x["chart_id"] for x in result.get("chart_specs", [])]
        if len(chart_keys) > 1:
            measure("chart_switch", lambda: app.selectbox(key="result_chart_selector").set_value(chart_keys[1]).run())
            notes["chart_switch"] = {"first": chart_keys[0], "second": chart_keys[1], "meaning": "switch existing aggregate ChartSpec; not new aggregation"}
        measure("overview_page", lambda: nav("分析概览"))
        measure("history_open", lambda: main_nav("history") if workbench else expand("guided_history"))
        measure("history_close", lambda: main_nav("workbench") if workbench else expand("guided_history", False))
        measure("report_page", lambda: nav("报告导出"))
        export_calls_before = counts["prepare_export_payload"]
        assert export_calls_before == 0
        for name, label in [("pdf", "生成 PDF 报告"), ("excel", "生成 Excel 报告")]:
            measure("export_"+name, lambda label=label: click(label))
        # Explicitly empty ONLY this session's export cache for the requested cold ZIP.
        # Full result/data caches and product budgets remain untouched.
        cache = app.session_state[exports.EXPORT_CACHE_KEY]
        notes["before_zip_cache_entries"] = len(cache)
        cache.clear()
        measure("export_zip_cold", lambda: click("生成 ZIP 报告包"))
        snapshot = app.session_state["performance_dataset"].current
        session = app.session_state["performance_result"]
        reference = {}
        for key, frame in result["result_tables"].items():
            reference[key] = {"columns": list(map(str, frame.columns)), "rows": json.loads(frame.to_json(orient="values", date_format="iso", double_precision=15))}
        args.output.with_suffix(".reference.json").write_text(json.dumps(reference, ensure_ascii=False, default=str)+"\n", encoding="utf-8")
        record = {"source": str(source), "python": sys.version, "platform": platform.platform(),
                  "packages": {name: metadata.version(name) for name in ["insightpilot-agent", "pandas", "numpy", "duckdb", "streamlit", "plotly", "scipy", "reportlab", "openpyxl", "sqlglot"]},
                  "scale": "standard", "seed": 42, "stages": stages, "phase_calls": phase_counts,
                  "total_calls": dict(counts), "function_seconds": dict(timings), "unrequested_exports": export_calls_before,
                  "tables": {name: {"rows": len(df), "columns": len(df.columns)} for name, df in snapshot.tables.items()},
                  "fingerprints": snapshot.fingerprints, "retained_dataset_bytes": snapshot.estimated_bytes,
                  "cache_policy": asdict(PerformanceConfig.from_environment()),
                  "result_cache": session.cache.stats(), "history_reserved_bytes": session.history_reserved_bytes,
                  "execution_status": result["execution_status"], "notes": notes, "hash_records": hash_records}
        for name, counters in phase_counts.items():
            if name in {"initial_data_ready", "analysis_first"} or name.startswith("export_"): continue
            for expensive in ["load_synthetic_tables", "infer_schema_mapping", "fingerprint_dataframe", "validate_dataframe_for_analysis", "run_agent_analysis", "_run_routed_analysis", "_run_playbook_node", "run_parameterized_sql", "request_work", "prepare_export_payload"]:
                assert counters.get(expensive, 0) == 0, (name, expensive, counters)
    record["memory"] = memory.summary()
    monkeypatch.undo()
    args.output.write_text(json.dumps(record, ensure_ascii=False, indent=2, default=str)+"\n", encoding="utf-8")
    print(json.dumps({"first": stages["analysis_first"], "prepare": stages["initial_data_ready"], "rss": record["memory"]["sampled_peak_bytes"]}), flush=True)
    return 0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--source-root", type=Path, default=ROOT)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--repeat", type=int, default=3)
    p.add_argument("--child", action="store_true")
    p.add_argument("--output", type=Path)
    args = p.parse_args()
    if args.child: return child(args)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    runs = []
    for iteration in range(args.repeat):
        target = (args.output_dir / f"run-{iteration+1}.json").resolve()
        command = [sys.executable, str(Path(__file__).resolve()), "--source-root", str(args.source_root.resolve()), "--output-dir", str(args.output_dir.resolve()), "--child", "--output", str(target)]
        env = dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1"); env.pop("PYTHONPATH", None)
        proc = subprocess.run(command, cwd=args.source_root, env=env, capture_output=True, text=True, encoding="utf-8", timeout=600)
        target.with_suffix(".stdout.txt").write_text(proc.stdout, encoding="utf-8")
        target.with_suffix(".stderr.txt").write_text(proc.stderr, encoding="utf-8")
        print(json.dumps({"iteration": iteration+1, "exit_code": proc.returncode, "record": str(target)}), flush=True)
        if proc.returncode: return proc.returncode
        runs.append(json.loads(target.read_text(encoding="utf-8")))
    def summary(values): return {"median": statistics.median(values), "min": min(values), "max": max(values)}
    result = {"method": "Fresh Python/AppTest per repetition; standard seed42; synchronous UI isolates rendering; first data preparation separate from first analysis. PDF and Excel requested separately, ZIP after explicit session export-cache clear. Native RSS every20ms. Test-only Streamlit1.63 expander event adapter; no result injection.",
              "source": str(args.source_root.resolve()), "repeats": len(runs),
              "stages": {key: summary([run["stages"][key] for run in runs]) for key in runs[0]["stages"]},
              "rss_peak_bytes": summary([run["memory"]["sampled_peak_bytes"] for run in runs]),
              "counts": [run["phase_calls"] for run in runs], "tables": runs[0]["tables"],
              "cache_policy": runs[0]["cache_policy"], "packages": runs[0]["packages"], "notes": runs[0]["notes"]}
    (args.output_dir/"summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    return 0

if __name__ == "__main__": raise SystemExit(main())
