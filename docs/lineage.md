# 数据血缘

## 模型

LineageGraph 由 DatasetNode、OperationNode 和 LineageEdge 组成，支持 JSON 与 DOT 文本输出。

## 数据节点

输入和输出节点记录名称、类型、行数、字段名与 deterministic fingerprint，不保存完整 DataFrame。

## 操作节点

操作节点记录分析类型、中文展示名、QueryPlan ID 和安全元数据。

## 派生关系

边记录 consumed_by、produced 等关系，用于说明结果由哪些输入和操作派生。

## 指纹

Lineage fingerprint 根据排序后的节点与边生成。相同血缘结构得到相同指纹，但指纹不能恢复原始数据。

## UI

专业模式展示输入表、操作、输出表、派生关系与指纹摘要；开发者模式额外展示原始 JSON 和 DOT 文本。

## 导出边界

血缘不包含明文凭据、完整数据库 URL、上传文件绝对路径或源文件内容。
