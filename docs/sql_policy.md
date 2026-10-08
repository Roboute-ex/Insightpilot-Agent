# SQL 策略与执行边界

软件版本仍为 **0.1.0**，SQL 策略版本为 `0.1.0-sql-2`。本轮沿用现有 SQLGlot 通路补强，没有叠加关键词黑名单，也没有替换分析引擎。实际安装及锁定版本为 SQLGlot 30.18.0。

## 校验与执行

`insightpilot.tools.sql_safety.validate_sql(query, allowed_tables, dialect, table_columns)` 返回不可变 `SQLValidationResult`：`allowed`、`dialect`、`statement_kind`、`referenced_tables`、`referenced_columns`、`functions`、`rejection_code`、中文 `reason`、`policy_version`。表引用来自 SQLGlot 作用域的实际来源；CTE 名和派生表别名不会当作物理表，另一个 UNION 分支中的同名 CTE 也不能遮住物理表。字段按每个作用域中的表别名、派生输出及相关子查询外层来源核对；歧义字段必须加限定名。

兼容入口 `validate_read_query` 仍返回 AST，拒绝时抛出携带上述结果的 `SQLPolicyError(ValueError)`。未提供 schema 的调用只作结构预检查，不能证明字段授权。DuckDB、LazyAnalyticsEngine、语义计划执行和 SQLite 的真正执行入口均提供本次已加载表及字段。未引入 AST 缓存，不存在跳过本次 schema 授权的缓存分支。

策略先要求完整单条 SELECT/WITH；结尾分号及其后注释通过词法 token 位置处理，字符串中的 `DROP`、`--`、`/* */` 是普通值。检查覆盖所有 CTE、子查询、集合分支，包含未被最终 SELECT 使用的 CTE。所有表节点必须能归属已认证的查询作用域。固定节点、算子及函数列表之外的结构默认拒绝，不以“解析成功”代替允许执行。

SQL 文本最多 65,536 字符、AST 最多 8,192 节点；递归 CTE、写入语句、SELECT INTO、系统目录、跨数据库限定符、路径表源、所有表函数、扩展及未授权 UDF 均拒绝。当前新增拒绝的结构包括 TABLESAMPLE、USING/NATURAL JOIN、物理表列重命名列表，以及带 EXCLUDE/REPLACE 扩展的星号。可分别改为已授权查询范围、明确 ON 条件、SELECT 字段别名和显式列列表；不为兼容不安全语法自动放宽策略。

参数只接收列表或字典形式的标量绑定值，不拼接用户值。语义编译器仍输出绑定参数；日期参数和含 SQL 关键词的普通字符串已分别回归。参数值不会出现在安全拒绝信息中。

## DuckDB 与 SQLite

本轮完整验证 DuckDB 和 SQLite。PostgreSQL、MySQL、MariaDB 的地址可以解析，但查询在连接前以 `UNSUPPORTED_DIALECT` 拒绝；不能把此前默认 DuckDB 解析当成外部数据库认证。恢复这些后端需补各自 schema 授权、只读事务、超时和原生方言的独立验收。

DuckDB 继续关闭外部访问、不允许未签名扩展，保留已有线程、内存、禁磁盘 spill 配置及查询超时。注册表时仅记录列名，不复制全量 DataFrame。LazyAnalyticsEngine 只为通过校验且实际引用的物理表创建连接并注册。

SQLite 仅以 `mode=ro` 打开已经存在的文件，启用 `query_only`，保留进度处理器超时；不会创建缺失数据库。内部元数据读取用于获取当前 main 数据库中的用户表/视图和字段，与用户 SQL 策略分离。执行期 authorizer 再次限制 SELECT、已授权字段读取和固定函数，阻止视图定义隐藏系统目录或未授权函数。用户 SQL 不能调用 PRAGMA；系统目录即使与 CTE 同名也不能越权读取。

两种执行入口均先校验原 SQL，再用换行隔离的子查询外包装限制为 `上限 + 1` 行，再以相同方言、表列范围和策略校验最终 SQL。只按经过词法确认的末尾分号位置切割，不重新生成原有表达式，不进行跨方言转换或通用优化。因此 SQLite 的 `5 / 2` 仍为整数 2，DuckDB 为 2.5；日期和 NULL 也按各自方言验证。包装或复验失败直接拒绝，不退回无限制 SQL。输出上限为 1–100,000 的整数；DuckDB 超限报错，SQLite 保留原有取数截断提示并明确本次分析范围。

取消保持协作边界：DuckDB 原生调用返回后由既有 trace 阶段检查，SQLite 在连接前、元数据完成后及取数后检查；取消/异常通过 finally 关闭连接。现有查询超时可以中断数据库调用，但用户取消不宣称即时强杀 native SQL。

## 失败、计划与测试

SQLGlot 不可用时模块仍可导入；受保护 SQL 返回 `DEPENDENCY_UNAVAILABLE`，提示按锁文件恢复依赖，不降级为正则继续执行。解析异常隐藏原始 SQL、字面值和地址。非查询、表/列越权、未知函数/节点、资源上限等有独立拒绝代码。

`QueryPlan.sql_policy_version` 进入计划标识、绑定指纹及输出；执行拒绝旧策略计划并要求重新编译。应用的相关缓存键同样纳入策略版本，策略变化不能沿用旧计划授权。此字段不改变软件 0.1.0，也不是数据库级 RLS 或多租户隔离承诺。

定向测试见 `tests/test_sql_policy.py`，覆盖单条/多条语句、CTE 同名及 UNION 后续分支、未知字段、Unicode/引号字段、相关子查询、派生表、COUNT(*)、绑定日期、结尾注释、字符串关键词、未知节点/函数、系统目录、视图隐藏目录、解析资源上限、依赖缺失、DuckDB/SQLite 独立数值语义、包装失败无回退、拒绝 SQL 的执行计数为 0、SQLite 缺失文件不创建、未认证方言不连接。已有 SQL、编译、取消和惰性执行测试继续运行；最终全量成绩以本轮实际 JUnit 和评估证据为准，不复用历史数量。

## 上游参考

2026-09-23 核对 SQLGlot 固定标签 `v30.18.0`，只采用已安装解析/词法/作用域公共 API 与独立编写策略，没有复制上游实现或使用通用 optimizer/transpile 自动改写业务查询。

- [SQLGlot v30.18.0 作用域实现](https://github.com/tobymao/sqlglot/blob/v30.18.0/sqlglot/optimizer/scope.py)：参考 `traverse_scope` 与 `Scope.selected_sources` 区分物理表和派生查询；不采用全局 CTE 名去除法。
- [SQLGlot v30.18.0 MIT 许可证](https://github.com/tobymao/sqlglot/blob/v30.18.0/LICENSE)：核实可使用该依赖，未新增上游代码复制归属。
- [SQLGlot 官方文档](https://sqlglot.com/sqlglot.html)：参考解析、AST 遍历与显式 read dialect；不宣称解析器提供权限系统或跨方言语义等价。
