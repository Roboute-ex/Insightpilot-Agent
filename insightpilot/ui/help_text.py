"""Short Chinese help text for professional analytics terms."""

HELP_TEXT_ZH_CN: dict[str, str] = {
    "analysis_goal_mode": "用于说明当前希望解决的分析问题。手动选择时优先于自动识别。",
    "playbook": "可复用的确定性分析流程，声明字段要求、参数、执行器、图表和输出章节。",
    "semantic_model": "用稳定定义连接实体、维度、度量、指标和表关系，避免任意文本生成 SQL。",
    "metric": "可复核的分析指标，由一个或多个聚合度量编译得到。",
    "measure": "对允许字段执行求和、计数、均值等基础聚合的定义。",
    "dimension": "用于分组、筛选或时间聚合的受控分析字段。",
    "entity": "语义模型中的分析对象，对应一张受控数据表及其粒度。",
    "join_fanout": "从一侧连接到多侧可能复制基础行，导致指标重复累计。",
    "query_plan": "包含指标依赖、Join 路径、参数化 SQL、风险和审批状态的稳定执行方案。",
    "data_contract": "对表、字段、主键、空值、范围和指标质量的可执行检查。",
    "lineage": "记录输入数据、执行操作和输出结果之间的派生关系。",
    "trace": "记录一次分析的节点路径、查询、警告、错误和审查上下文。",
    "run_manifest": "用于复核运行配置和数据指纹，不包含完整原始数据，也不能恢复原始输入。",
    "reviewer": "对计划、指标、安全边界、结果、限制和导出完整性进行确定性检查。",
    "cohort": "按首次发生时间分组，并观察各组在后续周期中的活跃或留存情况。",
    "funnel": "按顺序比较多个行为阶段的人数与转化率。",
    "causal_exploration": "使用有限控制变量进行假设探索，不能替代严谨的因果识别设计。",
}


def help_text(key: str) -> str:
    return HELP_TEXT_ZH_CN.get(key, key)
