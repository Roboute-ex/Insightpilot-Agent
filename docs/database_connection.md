# Database Connection

当前整合版 的 database ingestion 使用 SQLAlchemy 和 pandas，只执行只读查询。默认支持 SQLite；其他数据库需要用户自行安装对应 SQLAlchemy 驱动。

## SQLite 示例

```powershell
.\.venv\Scripts\python.exe examples/run_demo.py --data-source database --database-url sqlite:///local.db --query "SELECT * FROM metrics" --table-name db_table --goal-mode growth_trend
```

SQLite 文件不要提交到仓库，除非它是 tests/fixtures 下明确标注为 synthetic 的 tiny fixture。

## SQLAlchemy URL

示例格式：

```text
sqlite:///local.db
postgresql://user:password@host:5432/db
mysql+pymysql://user:password@host:3306/db
```

注意：

- 不要把真实 URL 或凭据写进 README、docs、trace、report 或 Git。
- UI/report 中展示 URL 时必须使用 `mask_database_url()`。
- 非 SQLite 数据库需要用户自行安装对应驱动。

## Read-only SQL 限制

只允许：

- `SELECT ...`
- `WITH ... SELECT ...`

禁止：

- DROP
- DELETE
- INSERT
- UPDATE
- ALTER
- CREATE
- TRUNCATE
- MERGE
- REPLACE
- GRANT
- REVOKE
- ATTACH
- DETACH
- COPY

也禁止分号连接多条 SQL。

## Secrets 管理建议

- 不要提交 `.streamlit/secrets.toml`。
- 不要提交 `.env` 或包含凭据的配置文件。
- 使用本地环境变量或本机会话输入管理连接信息。
- 报告中只记录 masked URL 或 source_name。

## 当前限制

- SQL safety 是保守字符串检查，不是完整 SQL parser。
- 默认最多读取 10000 行；如果 query 已包含 LIMIT，则保留用户 LIMIT。
- 查询结果只注册为当前 workflow 可用表，不默认写出文件。
