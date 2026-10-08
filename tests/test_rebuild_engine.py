"""Independent regression fixtures for recovered core behavior and boundaries."""
from __future__ import annotations
from dataclasses import replace
import io
import json
import sqlite3
import numpy as np
import pandas as pd
import pytest
from scipy import stats
from insightpilot.tools.duckdb_engine import AnalyticsEngine
from insightpilot.ingestion.db_loader import run_database_query, mask_database_url
from insightpilot.ingestion.file_loader import read_csv_file
from insightpilot.analysis.experiments import analyze_ab_test
from insightpilot.analysis.metric_diagnosis import _daily_series, compare_metric_baselines
from insightpilot.analysis.dimension_contribution import dimension_contribution_results
from insightpilot.analysis.funnel_decomposition import decompose_transaction_funnel, FUNNEL_STAGES
from insightpilot.semantic.compiler import MetricCompiler, execute_query_plan
from insightpilot.semantic.catalog import load_builtin_catalog
from insightpilot.semantic.query import MetricRequest, MetricFilter
from insightpilot.data.synthetic import generate_multi_table_commerce_data
from insightpilot.playbooks.executor import execute_playbook
from insightpilot.agents.workflow import run_agent_analysis
from insightpilot.reports.manifest import sanitize_manifest_value

@pytest.mark.parametrize("sql", [
    "SELECT * FROM read_csv_auto('secret.csv')", "SELECT * FROM read_parquet('https://example.invalid/data')",
    "SELECT * FROM sqlite_scan('secret.db','users')", "SELECT * FROM 'secret.csv'", "SELECT getenv('HOME')",
    "SELECT 1; /* comment */ SELECT 2", "WITH x AS (SELECT 1) DELETE FROM x", "SELECT * FROM unnest([1,2])",
])
def test_external_and_write_sql_is_rejected(sql):
    with AnalyticsEngine() as engine, pytest.raises(ValueError):
        engine.run_sql(sql)

def test_safe_quoted_values_comments_and_bound_scalars():
    with AnalyticsEngine() as engine:
        engine.register_tables({"t": pd.DataFrame({"name": ["DROP; --'", "normal"], "value": [2, 3]})})
        frame = engine.run_parameterized_sql('SELECT SUM("value") AS n FROM t WHERE name = ? /* safe */', ["DROP; --'"])
        assert frame.n.iloc[0] == 2
        with pytest.raises(ValueError):
            engine.run_sql("SELECT * FROM unregistered")

def test_duckdb_enforces_output_limit_and_external_access():
    with AnalyticsEngine(max_rows=2) as engine:
        engine.register_tables({"t": pd.DataFrame({"x": [1, 2, 3]})})
        with pytest.raises(ValueError):
            engine.run_sql("SELECT * FROM t")
        assert engine._connection.execute("SELECT current_setting('enable_external_access')").fetchone()[0] is False

def test_sqlite_missing_does_not_create_and_limit_is_enforced(tmp_path):
    missing = tmp_path / "missing.db"
    with pytest.raises(ValueError):
        run_database_query(f"sqlite:///{missing}", "SELECT 1")
    assert not missing.exists()
    path = tmp_path / "data.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE t(x INTEGER)")
        connection.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(9)])
    result = run_database_query(f"sqlite:///{path}", "SELECT * FROM t LIMIT 8", limit=3)
    assert len(result.dataframe) == 3 and any("截断" in w for w in result.warnings)
    with pytest.raises(ValueError):
        run_database_query(f"sqlite:///{path}", "DELETE FROM t")
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 9

def test_sqlite_error_and_metadata_hide_query_values(tmp_path):
    path = tmp_path / "data.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE t(x TEXT)")
        connection.execute("INSERT INTO t VALUES ('sensitive-value')")
    result = run_database_query(f"sqlite:///{path}", "SELECT * FROM t WHERE x='sensitive-value'")
    assert "sensitive-value" not in result.query
    with pytest.raises(ValueError) as error:
        run_database_query(f"sqlite:///{path}", "SELECT absent FROM t WHERE x='sensitive-value'")
    assert "sensitive-value" not in str(error.value) and str(path) not in str(error.value)
    assert "raw-token" not in mask_database_url("postgresql://u:pw@localhost/db?ssl_token=raw-token")

def test_csv_explicit_encoding_and_limit():
    source = io.BytesIO("城市,金额\n北京,3\n上海,4\n".encode("gbk"))
    loaded = read_csv_file(source, encoding="gbk", sep=",")
    assert loaded.dataframe["金额"].sum() == 7
    with pytest.raises(ValueError):
        read_csv_file(source, encoding="gbk", max_rows=1)

def test_weighted_ratio_zero_denominator_and_calendar_completeness():
    frame = pd.DataFrame({"date": ["2026-01-01"] * 2, "clicks": [1, 80], "impressions": [10, 100], "ctr": [.1, .8]})
    assert _daily_series(frame, "ctr").metric_value.iloc[0] == pytest.approx(81 / 110)
    frame.impressions = 0
    assert pd.isna(_daily_series(frame, "ctr").metric_value.iloc[0])
    history = pd.DataFrame({"date": pd.date_range("2026-01-01", periods=15), "orders": [10] * 14 + [20]})
    comparisons, _ = compare_metric_baselines(history.drop(index=12), "orders")
    assert comparisons[0].baseline_value == 10
    assert "6/7" in comparisons[0].confidence_note
    assert "零方差" in comparisons[0].confidence_note

def test_experiment_aggregates_units_and_welch_interval():
    frame = pd.DataFrame({"user_id": [1, 1, 2, 2, 3, 3, 4, 4], "group": ["control"] * 4 + ["treatment"] * 4, "value": [1, 3, 3, 5, 3, 5, 5, 7]})
    result = analyze_ab_test(frame, "group", "value")
    assert result["sample_size"] == {"control": 2, "treatment": 2}
    assert result["p_value"] == pytest.approx(2 * stats.t.sf(np.sqrt(2), 2))
    assert result["confidence_interval"] == pytest.approx([2 - stats.t.ppf(.975, 2) * np.sqrt(2), 2 + stats.t.ppf(.975, 2) * np.sqrt(2)])
    frame.loc[0, "group"] = "treatment"
    with pytest.raises(ValueError):
        analyze_ab_test(frame, "group", "value")

def test_proportion_requires_binary_and_zero_control_is_unavailable():
    with pytest.raises(ValueError):
        analyze_ab_test(pd.DataFrame({"group": ["control"] * 3 + ["treatment"] * 3, "value": [.1, .2, .3, .4, .5, .6]}), "group", "value", "proportion")
    result = analyze_ab_test(pd.DataFrame({"group": ["control"] * 3 + ["treatment"] * 3, "value": [0, 0, 0, 1, 2, 3]}), "group", "value")
    assert result["relative_lift"] is None

def test_funnel_sequential_impacts_conserve_signed_change():
    rows = [{"date": pd.Timestamp("2026-01-01") + pd.Timedelta(days=i), **dict(zip([x[0] for x in FUNNEL_STAGES], [1000, 800, 600, 400, 300, 200, 100] if i < 7 else [900, 720, 540, 360, 270, 180, 81]))} for i in range(8)]
    result = decompose_transaction_funnel(pd.DataFrame(rows))
    assert sum(row.estimated_order_impact for row in result) == pytest.approx(-19)
    assert sum(row.net_change_contribution for row in result) == pytest.approx(1)
    assert result[-1].residual_error == pytest.approx(0)

def test_rate_contribution_is_exact_within_each_dimension():
    rows = []
    for i in range(8):
        for city, clicks, impressions in [("A", 10 if i < 7 else 5, 20), ("B", 40, 80 if i < 7 else 180)]:
            rows.append({"date": pd.Timestamp("2026-01-01") + pd.Timedelta(days=i), "city": city, "clicks": clicks, "impressions": impressions, "ctr": clicks / impressions})
    result = dimension_contribution_results(pd.DataFrame(rows), "ctr", ["city"], include_drilldown=False)
    assert sum(row.contribution_value for row in result) == pytest.approx(45 / 200 - 50 / 100)

def test_semantic_approval_binds_data_and_rejects_additive_fanout():
    tables = generate_multi_table_commerce_data()
    compiler = MetricCompiler(load_builtin_catalog().get("commerce_demo"))
    request = MetricRequest(metrics=["customer_count"], dimensions=["order_status"])
    plan = compiler.compile(request, tables=tables)
    assert execute_query_plan(plan, tables, approved_plan_id=plan.plan_id)[0] is not None
    tables["orders"].loc[0, "total_amount"] += 1
    assert execute_query_plan(plan, tables, approved_plan_id=plan.plan_id)[1].decision == "rejected"
    fanout = compiler.compile(MetricRequest(metrics=["total_revenue"], dimensions=["product_category"]), tables=tables)
    assert not fanout.executable
    assert execute_query_plan(fanout, tables, approved_plan_id=fanout.plan_id)[0] is None

def test_semantic_rejects_duplicate_dimension_key_and_stable_preview_identity():
    tables = generate_multi_table_commerce_data()
    compiler = MetricCompiler(load_builtin_catalog().get("commerce_demo"))
    request = MetricRequest(metrics=["total_revenue"], dimensions=["customer_city"])
    preview = compiler.compile(replace(request, execution_mode="plan_only"), tables=tables)
    execute = compiler.compile(request, tables=tables)
    assert preview.plan_id == execute.plan_id
    tables["customers"] = pd.concat([tables["customers"], tables["customers"].iloc[[0]]], ignore_index=True)
    plan = compiler.compile(request, tables=tables)
    assert execute_query_plan(plan, tables)[1].decision == "rejected"

def test_preview_does_not_run_sql_or_statistics(monkeypatch):
    monkeypatch.setattr(AnalyticsEngine, "run_parameterized_sql", lambda *a, **k: pytest.fail("preview queried SQL"))
    result = run_agent_analysis("按城市查看金额", generate_multi_table_commerce_data(), playbook_id="semantic_metric_query", metric_request={"metrics": ["total_revenue"], "dimensions": ["customer_city"]}, plan_only=True)
    assert result["execution_status"] == "PREVIEW" and not result["result_tables"]
    assert result["reviewer"]["status"] != "PASS"

def test_funnel_uses_ordered_events_and_not_duplicate_rows():
    events = pd.DataFrame({"session_id": [1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2], "event_name": ["visit", "view", "cart", "submit", "paid", "paid", "paid", "visit", "view", "cart", "submit"], "event_time": pd.to_datetime(["2026-01-01 12:00", "2026-01-01 12:01", "2026-01-01 12:02", "2026-01-01 12:03", "2026-01-01 12:04", "2026-01-01 12:04", "2026-01-01 11:59", "2026-01-01 12:00", "2026-01-01 12:01", "2026-01-01 12:02", "2026-01-01 12:03"])})
    result = execute_playbook("funnel_analysis", {"events": events}, None)
    assert result.result_tables["funnel_summary"]["会话数"].tolist() == [2, 2, 2, 2, 1]

def test_cohort_marks_unmatured_windows_unobservable():
    tables = {"customers": pd.DataFrame({"customer_id": [1, 2], "signup_date": ["2026-01-05", "2026-01-12"]}), "sessions": pd.DataFrame({"customer_id": [1, 2], "session_date": ["2026-01-05", "2026-01-15"]})}
    result = execute_playbook("cohort_retention", tables, None, {"observation_periods": 3})
    frame = result.result_tables["cohort_retention"]
    assert len(frame) == 6 and frame.loc[~frame["可观察"], "留存率"].isna().all()
    assert frame.loc[frame["可观察"], "留存率"].tolist() == [1.0]

def test_sensitive_filters_are_redacted_and_must_be_reentered():
    model = load_builtin_catalog().get("commerce_demo")
    plan = MetricCompiler(model).compile(MetricRequest(metrics=["total_revenue"], filters=[MetricFilter("customer_city", "eq", "sensitive-city")]))
    serialized = json.dumps(plan.to_dict(), ensure_ascii=False, allow_nan=False)
    assert "sensitive-city" not in serialized
    with pytest.raises(ValueError):
        MetricRequest.from_dict(plan.to_dict()["request"])
    assert sanitize_manifest_value(float("nan")) is None

def test_approved_plan_rejects_mutated_parameters():
    tables = generate_multi_table_commerce_data()
    compiler = MetricCompiler(load_builtin_catalog().get("commerce_demo"))
    plan = compiler.compile(MetricRequest(metrics=["customer_count"], dimensions=["order_status"]), tables=tables)
    plan.parameters[-1] = 2
    assert execute_query_plan(plan, tables, approved_plan_id=plan.plan_id)[1].decision == "rejected"

def test_unsupported_forecast_has_no_fabricated_results():
    result = run_agent_analysis("请预测明天的宇宙颜色", generate_multi_table_commerce_data())
    assert result["execution_status"] == "UNSUPPORTED"
    assert result["planning_status"] == "unsupported"
    assert result["trace"]["executed_queries"] == []
    assert "UNSUPPORTED_ANALYSIS_GOAL" in {item["code"] for item in result["preflight"]["blocking_issues"]}
    assert not result["result_tables"] and result["reviewer"]["status"] != "PASS"

def test_freshness_uses_explicit_reference_and_string_dtype():
    from insightpilot.contracts import ColumnContract, TableContract, validate_contracts
    frame = pd.DataFrame({"name": pd.Series(["A"], dtype="string"), "date": ["2026-01-01"]})
    contract = TableContract("t", columns=[ColumnContract("name", data_type="string")], freshness_column="date", maximum_age_days=2, reference_time="2026-01-02")
    assert all(check.status == "PASS" for check in validate_contracts({"t": frame}, [contract]))
    assert any(check.status == "FAIL" for check in validate_contracts({"t": frame}, [replace(contract, reference_time=None)]))

def test_custom_mapped_trend_retains_actual_full_result_and_lineage():
    frame = pd.DataFrame({"date": pd.date_range("2026-01-01", periods=25), "sales": range(25)})
    result = run_agent_analysis("查看趋势", {"custom": frame}, goal_mode="growth_trend", data_source_type="uploaded_files", column_mapping={"table_name": "custom", "date_column": "date", "metric_columns": ["sales"], "aggregation": "mean"})
    assert len(result["result_tables"]["metric_trend"]) == 25
    assert result["result_tables"]["metric_trend"].sales.iloc[-1] == 24
    assert result["lineage"]["edges"] and result["lineage"]["operations"]

def test_langgraph_installed_node_failure_is_not_missing_dependency(monkeypatch):
    import insightpilot.agents.workflow as workflow
    import insightpilot.agents.langgraph_workflow as backend
    monkeypatch.setattr(workflow, "_langgraph_available", lambda: True)
    def fail(*args, **kwargs):
        raise ValueError("real node bug")
    monkeypatch.setattr(backend, "run_langgraph_workflow", fail)
    with pytest.raises(RuntimeError, match="LangGraph") as error:
        workflow.run_agent_analysis("查看金额", {}, use_langgraph=True)
    assert isinstance(error.value.__cause__, ValueError)

def test_live_association_pairs_actual_sessions_without_causal_claim():
    from insightpilot.analysis.associations import quality_conversion_association
    frame = pd.DataFrame({"session_id": [1,2,3,4], "user_id": [1,1,2,2], "stutter_rate": [0.,.1,.2,.3], "conversion_rate": [1.,1.,0.,0.], "device": ["A"]*4, "network_type": ["WiFi"]*4})
    result = quality_conversion_association(frame)
    row = result["quality_conversion_association"].iloc[0]
    assert row["pearson_correlation"] == pytest.approx(np.corrcoef([0,.1,.2,.3], [1,1,0,0])[0,1])
    assert row["sample_size"] == 4 and row["unique_users"] == 2
    assert "非独立用户" in row["limitations"] or "并非独立用户" in row["limitations"]
    assert len(result["quality_conversion_groups"]) == 1

def test_cumulative_metric_partitions_by_non_time_dimensions():
    compiler = MetricCompiler(load_builtin_catalog().get("commerce_demo"))
    # Two cities with unequal daily amounts: independent expected cumulative totals.
    tables = {"customers": pd.DataFrame({"customer_id": [1,2], "city": ["A","B"]}), "orders": pd.DataFrame({"order_id": [1,2,3,4], "customer_id": [1,2,1,2], "order_date": pd.to_datetime(["2026-01-01","2026-01-01","2026-01-02","2026-01-02"]), "total_amount": [10,100,20,200]})}
    plan = compiler.compile(MetricRequest(metrics=["cumulative_revenue", "total_revenue"], dimensions=["order_date", "customer_city"], date_dimension="order_date"), tables=tables)
    frame, review = execute_query_plan(plan, tables)
    assert review.decision == "approved"
    assert frame["cumulative_revenue"].tolist() == [10,100,30,300]
    assert "PARTITION BY" in plan.sql_template

def test_active_users_are_entity_distinct_not_summed_group_uv():
    frame = pd.DataFrame({"date": ["2026-01-01"]*3, "user_id": [1,1,2], "active_users": [1,1,1]})
    assert _daily_series(frame, "active_users").metric_value.iloc[0] == 2
    with pytest.raises(ValueError):
        _daily_series(frame.drop(columns="user_id"), "active_users")

def test_structured_sort_is_whitelisted_and_bound_to_plan():
    compiler = MetricCompiler(load_builtin_catalog().get("commerce_demo"))
    tables = {"orders": pd.DataFrame({"order_id": [1,2], "order_date": pd.to_datetime(["2026-01-01","2026-01-02"]), "total_amount": [10,30]})}
    request = MetricRequest(metrics=["total_revenue"], dimensions=["order_date"], sort=[{"field":"total_revenue","direction":"desc"}])
    plan = compiler.compile(request, tables=tables)
    result, review = execute_query_plan(plan, tables)
    assert review.decision == "approved" and result.total_revenue.tolist() == [30,10]
    ascending = compiler.compile(replace(request, sort=[{"field":"total_revenue","direction":"asc"}]), tables=tables)
    assert plan.plan_id != ascending.plan_id
    for invalid in [[{"field":"total_revenue; DROP TABLE orders","direction":"desc"}], [{"field":"total_revenue","direction":"DESC;"}], [{"field":"unknown","direction":"asc"}]]:
        with pytest.raises(ValueError):
            replace(request, sort=invalid)

def test_langgraph_schema_includes_every_workflow_field():
    from insightpilot.agents.state import WorkflowState
    from insightpilot.agents.langgraph_workflow import GraphState
    assert set(WorkflowState.__dataclass_fields__) == set(GraphState.__annotations__)

def test_dimension_top_positive_negative_limits_and_missing_days():
    rows=[]
    for i in range(8):
        if i == 3: continue
        for city in range(25):
            rows.append({"date":pd.Timestamp("2026-01-01")+pd.Timedelta(days=i),"city":str(city),"orders":10 if i<7 else 11+city})
    result=dimension_contribution_results(pd.DataFrame(rows),"orders",["city"],include_drilldown=False)
    named=[r for r in result if r.dimension_value!='Others']
    assert len(named)==5 and all(r.contribution_value>0 for r in named)
    assert all('6/7' in r.confidence_flag for r in result)
    assert sum(r.contribution_value for r in result)==sum(1+i for i in range(25))

def test_playbook_numeric_evidence_references_actual_result_rows():
    frame=pd.DataFrame({"date":pd.date_range('2026-01-01',periods=10),'sales':range(10)})
    result=run_agent_analysis('趋势',{'t':frame},playbook_id='metric_trend',column_mapping={'table_name':'t','date_column':'date','metric_columns':['sales']},data_source_type='uploaded_files')
    evidence=[e for e in result['analysis_result_package']['evidence'] if e['evidence_id'].startswith('RESULT-')]
    assert evidence
    assert any(e['supporting_values'].get('sales')==9 and e['supporting_values']['row_position']==9 for e in evidence)
    assert all(e['result_table'] in result['result_tables'] for e in evidence)


def _cross_fact_fixture():
    return {
        'customers': pd.DataFrame({'customer_id':[1,2,3], 'city':['A','B','C']}),
        'orders': pd.DataFrame({'order_id':[1,2,3], 'customer_id':[1,1,2], 'total_amount':[10.,20.,40.]}),
        'sessions': pd.DataFrame({'session_id':[1,2,3,4,5], 'customer_id':[1,1,1,3,3]}),
        'order_items': pd.DataFrame({'order_item_id':range(1,9), 'order_id':[1]*4+[2]*2+[3]*2}),
    }


def test_cross_fact_overall_aggregates_before_combining():
    compiler=MetricCompiler(load_builtin_catalog().get('commerce_demo'))
    tables=_cross_fact_fixture()
    request=MetricRequest(metrics=['total_revenue','session_count','revenue_per_session'])
    plan=compiler.compile(request,tables=tables)
    result,review=execute_query_plan(plan,tables)
    assert review.decision=='approved'
    assert result.iloc[0].tolist()==[70.,5.,14.]
    # Increasing item rows must not multiply order-level revenue or session count.
    tables['order_items']=pd.DataFrame({'order_item_id':range(100), 'order_id':[1]*100})
    result,review=execute_query_plan(compiler.compile(request,tables=tables),tables)
    assert review.decision=='approved' and result.iloc[0].tolist()==[70.,5.,14.]
    assert len(plan.join_plan.steps)==0


def test_cross_fact_common_dimensions_keep_sparse_groups_and_safe_ratio():
    compiler=MetricCompiler(load_builtin_catalog().get('commerce_demo'))
    tables=_cross_fact_fixture()
    request=MetricRequest(metrics=['total_revenue','session_count','revenue_per_session'],dimensions=['customer_city'])
    result,review=execute_query_plan(compiler.compile(request,tables=tables),tables)
    assert review.decision=='approved'
    rows=result.set_index('customer_city')
    assert rows.loc['A'].tolist()==[30.,3.,10.]
    assert rows.loc['B','total_revenue']==40 and rows.loc['B','session_count']==0
    assert pd.isna(rows.loc['B','revenue_per_session'])
    assert rows.loc['C'].tolist()==[0.,2.,0.]
    assert result.total_revenue.sum()==70 and result.session_count.sum()==5
    filtered=replace(request,filters=[MetricFilter('customer_city','eq','A')])
    assert execute_query_plan(compiler.compile(filtered,tables=tables),tables)[0].iloc[0].tolist()==['A',30.,3.,10.]
    limited=replace(request,sort=[{'field':'total_revenue','direction':'desc'}],limit=1)
    assert execute_query_plan(compiler.compile(limited,tables=tables),tables)[0].customer_city.tolist()==['B']


def test_cross_fact_incompatible_grains_and_changed_data_rejected():
    compiler=MetricCompiler(load_builtin_catalog().get('commerce_demo'))
    tables=_cross_fact_fixture()
    for dimensions in [['order_date'],['product_category'],['order_status']]:
        with pytest.raises(ValueError):
            compiler.compile(MetricRequest(metrics=['total_revenue','session_count'],dimensions=dimensions),tables=tables)
    plan=compiler.compile(MetricRequest(metrics=['revenue_per_session']),tables=tables)
    tables['orders'].loc[0,'total_amount']=999
    assert execute_query_plan(plan,tables)[1].decision=='rejected'


def test_semantic_preview_does_not_claim_analysis_or_charts_executed():
    result=run_agent_analysis('按城市比较金额',generate_multi_table_commerce_data(),playbook_id='semantic_metric_query',metric_request={'metrics':['total_revenue'],'dimensions':['customer_city'],'date_dimension':None},plan_only=True)
    assert result['execution_status']=='PREVIEW' and not result['trace']['executed_queries']
    assert result['query_plan']['executable'] and not result['errors']
    assert 'preview_playbook' in result['route_taken']
    assert not {'execute_playbook','execute_query_plan','generate_charts'}.intersection(result['route_taken'])


def test_cross_fact_workflow_preserves_full_request_and_filters():
    tables=generate_multi_table_commerce_data()
    city=str(tables['customers'].city.iloc[0])
    request={'metrics':['total_revenue','session_count','revenue_per_session'],'dimensions':['customer_city'],'date_dimension':None,'filters':[{'dimension_id':'customer_city','operator':'eq','value':city}]}
    result=run_agent_analysis('按城市比较金额与会话',tables,playbook_id='semantic_metric_query',metric_request=request)
    assert result['execution_status']=='COMPLETED',result['errors']
    actual=result['result_tables']['semantic_metric_result']
    customer_ids=set(tables['customers'].loc[tables['customers'].city==city,'customer_id'])
    revenue=tables['orders'].loc[tables['orders'].customer_id.isin(customer_ids),'total_amount'].sum()
    sessions=tables['sessions'].loc[tables['sessions'].customer_id.isin(customer_ids),'session_id'].nunique()
    assert len(actual)==1 and actual.customer_city.iloc[0]==city
    assert actual.total_revenue.iloc[0]==pytest.approx(revenue)
    assert actual.session_count.iloc[0]==sessions
    assert actual.revenue_per_session.iloc[0]==pytest.approx(revenue/sessions)
    assert result['query_plan']['request']['metrics']==request['metrics']
    preview=run_agent_analysis('跨事实日期未定义',tables,playbook_id='semantic_metric_query',metric_request={**request,'date_dimension':'order_date'},plan_only=True)
    assert preview['execution_status']=='FAILED' and not preview['trace']['executed_queries']
