from __future__ import annotations

from insightpilot.agents.workflow import run_agent_analysis
from insightpilot.data.synthetic import generate_multi_table_commerce_data


def test_three_multi_table_playbooks_pass_with_chinese_outputs() -> None:
    tables = generate_multi_table_commerce_data(seed=42)
    cases = {
        "semantic_metric_query": {"metric": "total_revenue", "dimensions": ["customer_city"]},
        "funnel_analysis": {},
        "cohort_retention": {},
    }
    for playbook_id, parameters in cases.items():
        result = run_agent_analysis("执行多表模拟分析", tables, playbook_id=playbook_id, playbook_parameters=parameters)
        assert result["playbook_result"]["status"] == "PASS"
        assert result["result_tables"]
        assert result["reviewer"]["status"] == "PASS"
    funnel = run_agent_analysis("分析漏斗", tables, playbook_id="funnel_analysis")
    assert "漏斗阶段" in funnel["result_tables"]["funnel_summary"].columns
    cohort = run_agent_analysis("分析留存", tables, playbook_id="cohort_retention")
    assert {"队列日期", "队列人数", "观察周期", "留存人数", "留存率"}.issubset(
        cohort["result_tables"]["cohort_retention"].columns
    )
