"""Validate bounded result selection against real server-owned group identities."""
from __future__ import annotations
from copy import deepcopy
from datetime import date
import hashlib
import json
import pandas as pd


def _key(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def city_candidates(result, node, snapshot):
    if node.run_id != str(result.get("run_manifest", {}).get("run_id")) or str(node.dataset_revision) != str(snapshot.revision):
        return []
    if result.get("execution_status") != "COMPLETED":
        return []
    table_key = "dimension_contributions"
    frame = result.get("result_tables", {}).get(table_key)
    if not isinstance(frame, pd.DataFrame) or not {"dimension", "dimension_value", "metric_id"}.issubset(frame.columns):
        return []
    config = node.config
    table_name = (config.get("column_mapping") or {}).get("table_name")
    if not table_name:
        table_name = "daily_metrics" if "daily_metrics" in snapshot.metadata else None
    meta = snapshot.metadata.get(table_name, {})
    facts = meta.get("readiness_summary", {}).get("columns", {}).get("city", {})
    # The legacy result holds string labels. Only exact, unambiguous typed keys
    # from the prepared metadata are safe to round-trip; never scan source here.
    if not facts.get("values_complete"):
        return []
    expected_fingerprint = result.get("run_manifest", {}).get("dataset_fingerprints", {}).get(table_name)
    if expected_fingerprint != snapshot.fingerprints.get(table_name):
        return []
    candidates = []
    for row in frame.loc[frame["dimension"].eq("city")].to_dict("records"):
        label = row["dimension_value"]
        if label == "Others":
            continue
        matches = [value for value in facts.get("values", []) if str(value) == str(label)]
        if len(matches) != 1:
            continue
        value = matches[0]
        payload = {"run_id":node.run_id, "dataset_id":snapshot.dataset_id, "dataset_revision":str(snapshot.revision),
            "table_key":table_key,"source_table":table_name,"metric_id":str(row["metric_id"]),
            "dimension":"city", "value":value}
        payload["group_key"] = _key([table_name,"city",type(value).__name__,value,payload["metric_id"]])
        candidates.append({"payload":payload,"label":str(value),"contribution_value":row.get("contribution_value"),"current_value":row.get("current_value")})
    return candidates[:50]


def validate_selection(payload, result, node, snapshot):
    if not isinstance(payload, dict):
        raise ValueError("分组选择事件无效。")
    for candidate in city_candidates(result, node, snapshot):
        if candidate["payload"] == payload:
            return deepcopy(candidate["payload"])
    raise ValueError("分组选择已失效或不属于当前运行、数据修订、指标和结果表；请重新选择。")


def build_drilldown_config(payload, result, node, snapshot):
    selection = validate_selection(payload, result, node, snapshot)
    config = deepcopy(node.config)
    mapping = deepcopy(config.get("column_mapping") or {})
    metadata = snapshot.metadata[selection["source_table"]]
    columns = metadata.get("columns", [])
    definition = next((item for item in result.get("metric_definitions", []) if item.get("metric_id") == selection["metric_id"]), {})
    aggregation = definition.get("aggregation") or mapping.get("aggregation") or "sum"
    mapping.update(table_name=selection["source_table"], source="user_selected", metric_columns=[selection["metric_id"]],
        dimension_columns=["city"], aggregation=aggregation, unit=definition.get("unit") or mapping.get("unit"),
        date_column=mapping.get("date_column") or ("date" if "date" in columns else None))
    previous = deepcopy(config.get("parameters", {}).get("exploration_request") or {})
    filters = deepcopy(previous.get("filters") or [])
    filters.append({"column":"city","operator":"eq","value":selection["value"]})
    request = {"kind":"grouped", "row_dimension":"city", "filters":filters,
        "top_n":20,"include_others":True,"max_display_rows":50,"max_display_columns":30,
        "date_from":previous.get("date_from"),"date_to":previous.get("date_to")}
    # Existing transaction contributions compare the target day with history.
    # This branch explicitly summarizes the selected city's target-day value.
    if not previous and (result.get("analysis_result_package", {}).get("metadata", {}).get("primary_baseline") == "previous_7d_average"):
        last = metadata.get("readiness_summary", {}).get("columns", {}).get(mapping.get("date_column"), {}).get("date_max")
        if last:
            request.update(date_from=str(last), date_to=str(last))
    config.update(question=f"按原指标口径查看所选城市 {selection['value']} 的描述性汇总", goal_mode="periodic_report",
        playbook_id="dimension_contribution", requested_playbook_id="dimension_contribution", effective_playbook_id="dimension_contribution",
        column_mapping=mapping, parameters={"exploration_request":request,"aggregation":aggregation}, selection_source="user_selected")
    for key in ("execution_mode","approved_plan_id","clarification_answers","request_fingerprint","semantic_fingerprint"):
        config.pop(key, None)
    return config
