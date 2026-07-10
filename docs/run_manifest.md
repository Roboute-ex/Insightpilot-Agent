# Run Manifest

RunManifest 用于保存一次分析的可复现配置和核对信息。它是 JSON 可序列化 dataclass，不是原始数据备份。

## 字段

主要字段包括 manifest/project version、run ID、created_at、data source、source summary、table summaries、dataset fingerprints、question、goal mode、workflow backend、playbook、parameters、Column Mapping、route、reviewer、caveats 和 errors。

## 数据指纹

`fingerprint_dataframe()` 使用列名、dtype、行数和稳定行哈希生成 SHA-256。相同 DataFrame 产生相同指纹，内容变化会改变指纹。

指纹用于判断输入是否变化，不可用于恢复原始数据，也不替代数据版本管理。

## 可复现范围

manifest 可以恢复问题、goal mode、playbook、参数和 mapping。重新运行仍需要用户重新提供相同输入数据。

manifest 不包含完整 DataFrame、数据库查询结果、上传文件内容或绝对路径。

## Config Import / Export

CLI 的 `--config-out` 输出安全 manifest JSON，`--config-in` 可以重新载入。包含 raw table data 的 config 会被拒绝。

Streamlit 在 Export tab 提供 Manifest JSON 下载，内容仅存在当前会话内存，除非用户主动下载。

## 版本兼容

当前 `manifest_version` 为 `1.0`。导入时检查主版本；不兼容版本返回清晰错误，不执行分析。

source summary 与 table summary 会遮罩 URL 密码和敏感字段，但仍建议只使用 synthetic 或已授权的本地测试数据。
