"""Run all ten playbooks in isolated source snapshots and compare complete results.

This supplements compatibility coverage; the before snapshot is not an independent
statistical oracle. Run from the current project with its existing virtualenv.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import traceback
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SINGLE = (
    "data_profile", "metric_trend", "period_comparison", "dimension_contribution",
    "experiment_comparison", "causal_exploration", "periodic_summary",
)
MULTI = {
    "semantic_metric_query": {"metric": "total_revenue", "dimensions": ["customer_city"]},
    "funnel_analysis": {},
    "cohort_retention": {},
}
# Exact path removal, not a recursive wildcard that could hide business fields.
EXCLUDED_PATHS = {"$.analysis_result_package.run_id": "Random UUID identifying this execution."}
RESULT_FIELDS = (
    "execution_status", "summary", "intent", "goal_mode", "metrics", "findings",
    "caveats", "reviewer", "errors", "column_mapping", "mapping_warnings",
    "schema_warnings", "playbook_parameters", "playbook_result",
    "analysis_result_package", "result_tables",
)


def dump(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize(value: Any, pd: Any) -> Any:
    """Lossless JSON scalar representation; never decimal-round or truncate rows."""
    if value is pd.NA:
        return {"$missing": "pd.NA"}
    if value is pd.NaT:
        return {"$missing": "NaT"}
    if isinstance(value, pd.DataFrame):
        return {
            "$type": "dataframe", "columns": [normalize(v, pd) for v in value.columns],
            "dtypes": [str(v) for v in value.dtypes],
            "index_names": [normalize(v, pd) for v in value.index.names],
            "index": [normalize(v, pd) for v in value.index.tolist()],
            "rows": [[normalize(v, pd) for v in row] for row in value.itertuples(index=False, name=None)],
        }
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if math.isnan(value):
            return {"$nonfinite": "nan"}
        if math.isinf(value):
            return {"$nonfinite": "+inf" if value > 0 else "-inf"}
        return value
    if isinstance(value, (dt.datetime, dt.date, pd.Timestamp)):
        return {"$datetime": value.isoformat()}
    if isinstance(value, (dt.timedelta, pd.Timedelta)):
        return {"$timedelta": str(value)}
    if isinstance(value, dict):
        return {str(key): normalize(item, pd) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalize(item, pd) for item in value]
    if hasattr(value, "item"):
        return normalize(value.item(), pd)
    if hasattr(value, "tolist"):
        return normalize(value.tolist(), pd)
    raise TypeError(f"Unsupported result type: {type(value).__module__}.{type(value).__name__}")


def strip_exact(value: Any, removed: list[str], path: str = "$") -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            item_path = path + "." + key
            if item_path in EXCLUDED_PATHS:
                removed.append(item_path)
            else:
                result[key] = strip_exact(item, removed, item_path)
        return result
    if isinstance(value, list):
        return [strip_exact(item, removed, f"{path}[{index}]") for index, item in enumerate(value)]
    return value


def compare(before: Any, after: Any, path: str = "$", column: str = "") -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    def error() -> None:
        errors.append({"path": path, "before": before, "after": after})
    if isinstance(before, bool) or isinstance(after, bool):
        if type(before) is not type(after) or before != after:
            error()
    elif isinstance(before, (int, float)) and isinstance(after, (int, float)):
        count_column = column in {"n", "control_n", "treatment_n", "total_n"} or any(
            text in column for text in ("sample_size", "row_count", "duplicate_rows", "_count", "人数", "会话数", "样本量")
        )
        exact = isinstance(before, int) and isinstance(after, int) or count_column
        equal = before == after if exact else math.isclose(
            before, after, rel_tol=1e-10, abs_tol=1e-300 if "p_value" in path else 1e-12
        )
        if not equal:
            error()
    elif isinstance(before, dict) and isinstance(after, dict):
        if set(before) != set(after):
            errors.append({"path": path, "before_keys": sorted(before), "after_keys": sorted(after)})
        frame = before.get("$type") == after.get("$type") == "dataframe"
        for key in sorted(before.keys() & after.keys()):
            if frame and key == "rows":
                arows, brows = before[key], after[key]
                if len(arows) != len(brows):
                    errors.append({"path": path + ".rows", "before_length": len(arows), "after_length": len(brows)})
                for index, (arow, brow) in enumerate(zip(arows, brows)):
                    if len(arow) != len(brow):
                        errors.append({"path": f"{path}.rows[{index}]", "before_width": len(arow), "after_width": len(brow)})
                    for col_index, (avalue, bvalue) in enumerate(zip(arow, brow)):
                        col = str(before["columns"][col_index])
                        errors.extend(compare(avalue, bvalue, f"{path}.rows[{index}].{col}", col))
            else:
                errors.extend(compare(before[key], after[key], path + "." + key, key))
    elif isinstance(before, list) and isinstance(after, list):
        if len(before) != len(after):
            errors.append({"path": path, "before_length": len(before), "after_length": len(after)})
        for index, (avalue, bvalue) in enumerate(zip(before, after)):
            errors.extend(compare(avalue, bvalue, f"{path}[{index}]", column))
    elif type(before) is not type(after) or before != after:
        error()
    return errors


def comparator_checks() -> dict[str, bool]:
    checks = {
        "tiny_p_value_cannot_become_zero": bool(compare(1.4e-25, 0.0, "$.p_value", "p_value")),
        "count_change_rejected": bool(compare(6000, 6001, "$.sample_size", "sample_size")),
        "evidence_deletion_rejected": bool(compare({"evidence": [{"value": 2.0}]}, {"evidence": []})),
        "missing_and_zero_distinct": bool(compare({"$nonfinite": "nan"}, 0.0)),
        "float_roundoff_within_tolerance": not compare(1.0, 1.0 + 1e-13),
    }
    if not all(checks.values()):
        raise AssertionError(checks)
    return checks


def child(args: argparse.Namespace) -> int:
    source = args.source_root.resolve()
    sys.path.insert(0, str(source))
    import pandas as pd
    import insightpilot.agents.workflow as workflow
    from insightpilot.data.synthetic import generate_multi_table_commerce_data

    fixture_path = args.fixture_root.resolve() / "tests/conftest.py"
    spec = importlib.util.spec_from_file_location("playbook_snapshot_fixture", fixture_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load fixed test fixture")
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    single_tables = fixture.playbook_tables.__wrapped__()
    mapping = fixture.playbook_mapping.__wrapped__()
    multi_tables = generate_multi_table_commerce_data(seed=42)
    all_cases = []
    for playbook in (*SINGLE, *MULTI):
        tables = single_tables if playbook in SINGLE else multi_tables
        # Each workflow receives fresh fixture copies, so earlier analysis cannot
        # change the input to a later playbook on either source snapshot.
        tables = {name: frame.copy(deep=True) for name, frame in tables.items()}
        description = {
            "playbook_id": playbook,
            "fixture": "tests/conftest.py::playbook_tables + playbook_mapping" if playbook in SINGLE else "tests/test_multi_table_playbooks_v06.py::test_three_multi_table_playbooks_pass_with_chinese_outputs",
            "parameters": {} if playbook in SINGLE else MULTI[playbook],
            "mapping": mapping if playbook in SINGLE else None,
        }
        input_summary = {}
        for name, frame in tables.items():
            serialized = json.dumps(normalize(frame, pd), ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            input_summary[name] = {"rows": len(frame), "columns": list(map(str, frame.columns)), "sha256": hashlib.sha256(serialized.encode("utf-8")).hexdigest()}
        case: dict[str, Any] = {"configuration": description, "inputs": input_summary}
        try:
            kwargs = {"playbook_id": playbook, "playbook_parameters": description["parameters"]}
            if playbook in SINGLE:
                kwargs.update(column_mapping=mapping, data_source_type="uploaded_files")
            if args.confirm_experiment_fixture and playbook in {"experiment_comparison", "causal_exploration"}:
                import inspect
                confirmation = {"control_value": "control", "treatment_value": "treatment"}
                if playbook == "experiment_comparison":
                    confirmation["statistical_unit"] = "row"
                case["fixture_confirmation"] = {"values": confirmation, "basis": "The fixed tests/conftest.py fixture contains one independent generated outcome per row. This supplies the newly required explicit assumption, without changing rows or statistical expected values."}
                if "clarification_answers" in inspect.signature(workflow.run_agent_analysis).parameters:
                    kwargs["clarification_answers"] = confirmation
            result = workflow.run_agent_analysis("执行多表模拟分析" if playbook in MULTI else "执行测试分析剧本", tables, **kwargs)
            payload = normalize({field: result[field] for field in RESULT_FIELDS}, pd)
            removed: list[str] = []
            case["payload"] = strip_exact(payload, removed)
            case["excluded_paths"] = removed
            case["successful_execution"] = result["execution_status"] == "COMPLETED" and result["playbook_result"]["status"] in {"PASS", "WARN"} and bool(result["result_tables"])
            case["result_table_rows"] = {name: len(frame) for name, frame in result["result_tables"].items()}
        except Exception:
            case["successful_execution"] = False
            case["error"] = traceback.format_exc()
        all_cases.append(case)
        print(json.dumps({"playbook": playbook, "successful_execution": case["successful_execution"]}), flush=True)
    imports = {name: str(Path(module.__file__).resolve()) for name, module in sys.modules.items() if name == "insightpilot" or name.startswith("insightpilot.") if getattr(module, "__file__", None)}
    wrong = {name: filename for name, filename in imports.items() if not Path(filename).is_relative_to(source)}
    if wrong:
        raise RuntimeError(f"Source isolation failed: {wrong}")
    dump(args.child_output, {"source_root": str(source), "source_file": workflow.__file__, "pid": os.getpid(), "python": sys.version, "fixture_path": str(fixture_path), "fixture_sha256": digest(fixture_path), "imported_product_files": imports, "cases": all_cases})
    return int(any(not case["successful_execution"] for case in all_cases))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, default=ROOT / "reports/performance/source-before/insightpilot-agent")
    parser.add_argument("--after", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=ROOT / "reports/performance/playbook-comparison.json")
    parser.add_argument("--timeout", type=int, default=240, help="Per source child timeout in seconds")
    parser.add_argument("--confirm-experiment-fixture", action="store_true", help="Explicitly confirm the existing independent-row fixture and control/treatment direction; preserve all strict differences.")
    parser.add_argument("--reuse-artifacts", type=Path, help="Compare saved before.json/after.json without executing code again")
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--source-root", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--fixture-root", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--child-output", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child:
        return child(args)
    args.output = args.output.resolve()
    if args.reuse_artifacts is not None:
        args.reuse_artifacts = args.reuse_artifacts.resolve()
    checks = comparator_checks()
    if args.output.exists():
        raise FileExistsError(f"Preserving existing report; choose another --output: {args.output}")
    for source in (args.before, args.after):
        if not (source / "insightpilot/agents/workflow.py").is_file():
            raise FileNotFoundError(source)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    artifacts = args.reuse_artifacts or args.output.parent / (args.output.stem + "-" + stamp)
    if not args.reuse_artifacts:
        artifacts.mkdir(parents=True, exist_ok=False)
    child_records, failures = {}, []
    for label, source in (("before", args.before), ("after", args.after)):
        output = artifacts / (label + ".json")
        if args.reuse_artifacts:
            child_records[label] = json.loads(output.read_text(encoding="utf-8"))
            if Path(child_records[label]["source_root"]).resolve() != source.resolve():
                raise ValueError("Saved source root differs from requested source root")
            continue
        command = [sys.executable, "-B", str(Path(__file__).resolve()), "--child", "--source-root", str(source.resolve()), "--fixture-root", str(args.before.resolve()), "--child-output", str(output)]
        if args.confirm_experiment_fixture:
            command.append("--confirm-experiment-fixture")
        environment = dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
        try:
            process = subprocess.run(command, cwd=source, env=environment, capture_output=True, text=True, encoding="utf-8", timeout=args.timeout, check=False)
            (artifacts / (label + ".stdout.txt")).write_text(process.stdout, encoding="utf-8")
            (artifacts / (label + ".stderr.txt")).write_text(process.stderr, encoding="utf-8")
            if process.returncode:
                failures.append({"source": label, "returncode": process.returncode, "stderr_file": str(artifacts / (label + ".stderr.txt"))})
            if output.exists():
                child_records[label] = json.loads(output.read_text(encoding="utf-8"))
        except subprocess.TimeoutExpired:
            failures.append({"source": label, "error": "Child timed out", "timeout_seconds": args.timeout})
    records = []
    if set(child_records) == {"before", "after"}:
        before = {case["configuration"]["playbook_id"]: case for case in child_records["before"]["cases"]}
        after = {case["configuration"]["playbook_id"]: case for case in child_records["after"]["cases"]}
        for playbook in (*SINGLE, *MULTI):
            old, new = before[playbook], after[playbook]
            differences = compare(old, new, "$." + playbook)
            # Keep display changes in the strict comparison; never call them random metadata.
            prefix = "$." + playbook + ".payload.analysis_result_package.chart_specs"
            presentation_differences = [item for item in differences if item["path"] == prefix or item["path"].startswith(prefix + "[") or item["path"].startswith(prefix + ".")]
            statistical_differences = [item for item in differences if item not in presentation_differences]
            successful = old["successful_execution"] and new["successful_execution"]
            numerical_differences = compare(old.get("payload", {}).get("result_tables", {}), new.get("payload", {}).get("result_tables", {}), "$." + playbook + ".payload.result_tables")
            for field in ("metric_comparisons", "anomalies", "funnel_results", "dimension_contributions", "experiment_results", "evidence", "recommendations"):
                numerical_differences.extend(compare(old.get("payload", {}).get("analysis_result_package", {}).get(field), new.get("payload", {}).get("analysis_result_package", {}).get(field), "$." + playbook + ".payload.analysis_result_package." + field))
            records.append({"playbook_id": playbook, "numerical_evidence_compatible": successful and not numerical_differences, "numerical_evidence_difference_count": len(numerical_differences), "numerical_evidence_differences": numerical_differences, "successful_execution": successful, "table_count": len(old.get("result_table_rows", {})), "table_rows": old.get("result_table_rows", {}), "evidence_count": len(old.get("payload", {}).get("analysis_result_package", {}).get("evidence", [])), "inputs_identical": not compare(old["inputs"], new["inputs"]), "passed": successful and not statistical_differences, "strict_payload_identical": not differences, "difference_count": len(statistical_differences), "differences": statistical_differences, "presentation_difference_count": len(presentation_differences), "presentation_differences": presentation_differences})
    passed = len(records) == 10 and all(record["passed"] for record in records) and not failures
    report = {
        "passed": passed,
        "numerical_evidence_compatible": len(records) == 10 and all(record["numerical_evidence_compatible"] for record in records) and not failures,
        "numerical_evidence_difference_count": sum(record["numerical_evidence_difference_count"] for record in records),
        "fixture_confirmation_requested": args.confirm_experiment_fixture,
        "numerical_comparison_policy": "Every complete result table (schema, dtype, index and ordered cells) and every structured metric comparison, anomaly, funnel, contribution, experiment result, evidence and recommendation is compared. New protocol/definition/mapping/SQL-policy metadata remains in the full strict differences; no difference is relabeled random. The optional explicit row-unit confirmation only addresses the declared fixture assumption required by the new planner.",
        "purpose": "Compatibility regression against an exact pre-performance source snapshot, not independent statistical ground truth.",
        "before": str(args.before.resolve()), "after": str(args.after.resolve()), "artifacts": str(artifacts.resolve()),
        "script_sha256": digest(Path(__file__)), "comparator_checks": checks,
        "method": "Two sequential isolated Python subprocesses, source import paths verified; fixed before tests/conftest.py fixtures; seed 42 multi-table fixture; input SHA256 equality required; complete result table names, columns, dtypes, indices, ordered rows and nested analysis-package evidence compared. No rows truncated or float values rounded. Counts exact, float rtol=1e-10/atol=1e-12, p_value atol=1e-300. No expected values updated.",
        "compared_workflow_fields": list(RESULT_FIELDS), "excluded_exact_paths": EXCLUDED_PATHS,
        "presentation_comparison_policy": "analysis_result_package.chart_specs is compared and retained in presentation_differences, separately from numerical/evidence compatibility. Added display-budget metadata is deterministic new functionality, not random metadata. A compatible numeric payload does not imply a strictly identical presentation payload.",
        "outside_comparison_scope": "Figures, rendered Markdown/PDF/HTML, trace/telemetry timing and UUID metadata, manifest, lineage and duplicate workflow_state are not the numeric/evidence payload. No business field, result table or evidence item is removed from the selected payload; chart_specs inside analysis_result_package and playbook_result are retained.",
        "fixture_sources": ["tests/conftest.py", "tests/test_playbook_executor.py::test_builtin_playbook_executes", "tests/test_multi_table_playbooks_v06.py::test_three_multi_table_playbooks_pass_with_chinese_outputs"],
        "playbook_count": len(records), "table_count": sum(record["table_count"] for record in records),
        "difference_count": sum(record["difference_count"] for record in records), "process_failures": failures,
        "strict_payload_identical": len(records) == 10 and all(record["strict_payload_identical"] for record in records),
        "presentation_difference_count": sum(record["presentation_difference_count"] for record in records),
        "checks": records,
    }
    dump(args.output, report)
    print(json.dumps({key: report[key] for key in ("passed", "playbook_count", "table_count", "difference_count", "process_failures")}, ensure_ascii=False))
    return int(not passed)


if __name__ == "__main__":
    raise SystemExit(main())
