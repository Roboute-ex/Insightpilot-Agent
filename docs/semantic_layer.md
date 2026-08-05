# Semantic Layer

## 组成

语义层由 SemanticModel、SemanticCatalog、SemanticEntity、SemanticDimension、SemanticMeasure 和 SemanticMetric 组成。

## 模型加载

内置 YAML 位于 `insightpilot/semantic/models/`，仅通过 `yaml.safe_load` 读取。模型注册前必须验证实体、指标依赖和关系引用。

## 指标类型

- simple：对 allowlisted 度量执行聚合。
- ratio：用安全除零表达式组合两个指标。
- derived：使用受限加减乘除操作组合指标。
- cumulative：按明确时间维度计算累计值。

## 稳定 schema

模型 ID、字段名和 JSON key 使用英文。中文名称只作为 display_name 和 UI presenter 输出。

## 安全编译

MetricCompiler 只使用模型中的表名与字段名。筛选值、日期和 limit 使用参数绑定，不接受 SQL fragment 或任意 Text-to-SQL。

## 校验命令

```powershell
.\.venv\Scripts\python.exe -m insightpilot.semantic.validate
```

相同模型和 MetricRequest 必须生成相同 QueryPlan ID。
