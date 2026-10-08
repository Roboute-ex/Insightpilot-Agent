"""One fail-closed SQL policy. SQLGlot is a parser, not an authorization sandbox."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

try:
    from sqlglot import exp, parse, Dialect
    from sqlglot.optimizer.scope import Scope, traverse_scope
    from sqlglot.tokens import TokenType
except ImportError:
    exp = parse = Scope = traverse_scope = TokenType = Dialect = None

SQL_POLICY_VERSION = "0.1.0-sql-2"
MAX_SQL_LENGTH = 65536
MAX_AST_NODES = 8192
SUPPORTED_DIALECTS = frozenset({"duckdb", "sqlite"})
SAFE_FUNCTIONS = frozenset({
    "SUM", "COUNT", "AVG", "MIN", "MAX", "ABS", "ROUND", "COALESCE", "NULLIF",
    "CAST", "TRY_CAST", "DATE_TRUNC", "TIMESTAMP_TRUNC", "STDDEV_SAMP", "STDDEV",
    "VARIANCE", "VAR_SAMP", "SQRT", "POWER", "LOWER", "UPPER", "LENGTH",
    "SUBSTRING", "TRIM", "EXTRACT", "STRFTIME", "IF", "CASE", "IFNULL", "AND", "OR",
    "DATE", "TIME", "DATETIME", "JULIANDAY", "UNIXEPOCH", "TIME_TO_STR",
    "TS_OR_DS_TO_TIMESTAMP", "CURRENT_DATE", "CURRENT_TIMESTAMP", "CURRENT_TIME",
    "EXISTS", "ROW_NUMBER", "RANK", "DENSE_RANK", "LAG", "LEAD", "FIRST_VALUE", "LAST_VALUE",
    "QUANTILE_CONT", "PERCENTILE_CONT",  # SQLGlot canonicalizes DuckDB quantiles. Exact numeric quantiles for explicit bounded exploration.
    "CEIL", "FLOOR", "CONCAT", "GREATEST", "LEAST", "DATE_DIFF", "DATEDIFF",
})
SAFE_NODES = frozenset({
    "Select", "Union", "Intersect", "Except", "Subquery", "With", "CTE", "Table",
    "TableAlias", "Identifier", "Column", "Star", "Alias", "From", "Join", "Where",
    "Group", "Having", "Order", "Ordered", "Limit", "Offset", "Distinct", "Window",
    "WindowSpec", "Filter", "WithinGroup", "Paren", "Literal", "Boolean", "Null",
    "Placeholder", "Parameter", "Var", "DataType", "DataTypeParam", "Interval",
    "Neg", "Add", "Sub", "Mul", "Div", "Mod", "Pow", "And", "Or", "Not", "EQ",
    "NEQ", "LT", "LTE", "GT", "GTE", "NullSafeEQ", "NullSafeNEQ", "Is", "Between",
    "In", "Like", "ILike", "Escape", "Exists", "Case", "If",
})

@dataclass(frozen=True)
class SQLValidationResult:
    allowed: bool
    dialect: str
    statement_kind: str = "unknown"
    referenced_tables: tuple[str, ...] = ()
    referenced_columns: tuple[str, ...] = ()
    functions: tuple[str, ...] = ()
    rejection_code: str | None = None
    reason: str = "SQL 结构及本次授权范围校验通过。"
    policy_version: str = SQL_POLICY_VERSION
    _tree: Any = field(default=None, repr=False, compare=False)

    def to_dict(self) -> dict[str, Any]:
        return {key: getattr(self, key) for key in (
            "allowed", "dialect", "statement_kind", "referenced_tables",
            "referenced_columns", "functions", "rejection_code", "reason", "policy_version",
        )}

class SQLPolicyError(ValueError):
    def __init__(self, validation: SQLValidationResult):
        self.validation = validation
        super().__init__(f"SQL 安全检查未通过 [{validation.rejection_code}]：{validation.reason}")

class _Denied(Exception):
    def __init__(self, code: str, reason: str):
        self.code, self.reason = code, reason

def _deny(code: str, reason: str) -> None:
    raise _Denied(code, reason)

def _system_table(name: str) -> bool:
    value = name.casefold()
    return value.startswith(("sqlite_", "pg_", "duckdb_")) or value in {"information_schema", "sys", "system"}

def _validate_scopes(tree, allowed_tables, table_columns):
    scopes = traverse_scope(tree)
    authorized = None if allowed_tables is None else {str(x).casefold() for x in allowed_tables}
    schemas = None if table_columns is None else {str(k).casefold(): list(map(str, v)) for k, v in table_columns.items()}
    physical, columns = set(), set()
    source_cache, output_cache, resolving = {}, {}, set()
    resolved_table_nodes = set()

    def sources(scope):
        if id(scope) in source_cache:
            return source_cache[id(scope)]
        found = {}
        for alias, (node, source) in scope.selected_sources.items():
            if isinstance(node, exp.Table):
                resolved_table_nodes.add(id(node))
            key = alias.casefold()
            if key in found:
                _deny("AMBIGUOUS_SOURCE", "同一作用域存在重复表别名。")
            if isinstance(source, exp.Table):
                name = source.name
                if _system_table(name):
                    _deny("SYSTEM_CATALOG", "系统目录未获授权。内部元数据读取与用户 SQL 分离。")
                if authorized is not None and name.casefold() not in authorized:
                    _deny("TABLE_NOT_ALLOWED", "查询引用了本次范围以外的物理表。")
                physical.add(name)
                names = None if schemas is None else schemas.get(name.casefold())
                if schemas is not None and names is None:
                    _deny("MISSING_SCHEMA", "物理表缺少已加载字段定义，拒绝执行。")
                if node.args.get("alias") and node.args["alias"].args.get("columns"):
                    _deny("UNSUPPORTED_TABLE_ALIAS", "物理表字段重命名列表尚未认证，请使用 SELECT 别名。")
                found[key] = (names, source)
            elif isinstance(source, Scope):
                found[key] = (outputs(source), source)
            else:
                _deny("UNSUPPORTED_SOURCE", "不支持该数据源；表函数未获授权。")
        source_cache[id(scope)] = found
        return found

    def outputs(scope):
        if id(scope) in output_cache:
            return output_cache[id(scope)]
        if id(scope) in resolving:
            _deny("RECURSIVE_SCOPE", "不允许递归或循环查询作用域。")
        resolving.add(id(scope))
        if scope.outer_columns:
            names = list(scope.outer_columns)
        elif isinstance(scope.expression, (exp.Union, exp.Intersect, exp.Except)):
            names = outputs(scope.union_scopes[0])
        else:
            names = []
            for selected in scope.expression.selects:
                if isinstance(selected, exp.Star):
                    for available, _ in sources(scope).values():
                        if available is None:
                            names = None
                            break
                        names.extend(available)
                elif isinstance(selected, exp.Column) and selected.is_star:
                    entry = sources(scope).get(selected.table.casefold())
                    if entry is None:
                        _deny("UNKNOWN_SOURCE_ALIAS", "星号引用了未知表别名。")
                    if entry[0] is None:
                        names = None
                    else:
                        names.extend(entry[0])
                else:
                    name = selected.alias_or_name
                    if name:
                        names.append(name)
                if names is None:
                    break
        resolving.discard(id(scope))
        output_cache[id(scope)] = names
        return names

    def resolve(scope, column):
        local = sources(scope)
        name, qualifier = column.name.casefold(), column.table.casefold()
        if column.db or column.catalog:
            _deny("QUALIFIED_CATALOG", "列的数据库或目录限定符越过当前范围。")
        if qualifier:
            candidates = [local[qualifier]] if qualifier in local else []
        else:
            candidates = [entry for entry in local.values() if entry[0] is None or name in {x.casefold() for x in entry[0]}]
        if schemas is None and not qualifier:
            return  # A preflight cannot resolve columns without a registry.
        if len(candidates) > 1:
            _deny("AMBIGUOUS_COLUMN", "字段属于多个来源，请使用表别名限定。")
        if candidates:
            available, source = candidates[0]
            if available is not None and sum(x.casefold() == name for x in available) != 1:
                _deny("COLUMN_NOT_ALLOWED", "字段不存在或在该来源中不唯一。")
            if isinstance(source, exp.Table):
                columns.add(f"{source.name}.{column.name}")
            return
        if not qualifier:
            aliases = {x.alias.casefold() for x in scope.expression.selects if x.alias}
            parent = column.parent
            while parent is not None and parent is not scope.expression:
                if isinstance(parent, (exp.Group, exp.Having, exp.Order)) and name in aliases:
                    return
                parent = parent.parent
        if scope.can_be_correlated and scope.parent is not None:
            resolve(scope.parent, column)
            return
        if schemas is None and not qualifier and local:
            return  # Structural preflight is not execution authorization.
        _deny("COLUMN_NOT_ALLOWED", "字段或限定别名不在该来源的字段定义中。")

    for scope in scopes:
        sources(scope)
        if isinstance(scope.expression, (exp.Union, exp.Intersect, exp.Except)):
            names = outputs(scope)
            if schemas is not None:
                for column in scope.columns:
                    if column.table or names is None or sum(x.casefold() == column.name.casefold() for x in names) != 1:
                        _deny("COLUMN_NOT_ALLOWED", "集合查询排序字段不在输出列中。")
            continue
        for column in scope.columns:
            resolve(scope, column)
        for selected in [*scope.expression.selects, *scope.stars]:
            if isinstance(selected, exp.Star):
                entries = sources(scope).values()
            elif isinstance(selected, exp.Column) and selected.is_star:
                alias = selected.table.casefold()
                if alias not in sources(scope):
                    _deny("UNKNOWN_SOURCE_ALIAS", "星号引用了未知表别名。")
                entries = [sources(scope)[alias]]
            else:
                continue
            for names, source in entries:
                if isinstance(source, exp.Table) and names is not None:
                    columns.update(f"{source.name}.{name}" for name in names)
    if any(id(node) not in resolved_table_nodes for node in tree.find_all(exp.Table)):
        _deny("UNRESOLVED_SOURCE", "存在未能归属已认证查询作用域的数据源。")
    return tuple(sorted(physical)), tuple(sorted(columns))

def validate_sql(query: str, allowed_tables: set[str] | None = None, dialect: str = "duckdb",
                 table_columns: Mapping[str, Sequence[str]] | None = None) -> SQLValidationResult:
    """Validate without execution; schema may be omitted only for preflight."""
    kind, functions = "unknown", set()
    try:
        if exp is None or parse is None:
            _deny("DEPENDENCY_UNAVAILABLE", "SQLGlot 不可用，请按锁文件恢复依赖；SQL 已停止。")
        if dialect not in SUPPORTED_DIALECTS:
            _deny("UNSUPPORTED_DIALECT", "本轮仅认证 DuckDB 与 SQLite；其他数据库执行已停用。")
        if not isinstance(query, str) or not query.strip():
            _deny("EMPTY_QUERY", "查询不能为空。")
        if len(query) > MAX_SQL_LENGTH:
            _deny("SQL_TOO_LARGE", f"SQL 超过 {MAX_SQL_LENGTH} 字符上限。")
        tokens = Dialect.get_or_raise(dialect).tokenize(query)
        if not tokens or tokens[0].token_type not in {TokenType.SELECT, TokenType.WITH}:
            _deny("STATEMENT_NOT_READ_ONLY", "仅允许单条 SELECT/WITH 查询。")
        separators = [i for i, token in enumerate(tokens) if token.token_type == TokenType.SEMICOLON]
        if separators and separators != [len(tokens) - 1]:
            _deny("MULTIPLE_STATEMENTS", "只允许一条查询及可选的结尾分号。")
        statements = [x for x in parse(query, read=dialect) if x is not None and not isinstance(x, exp.Semicolon)]
        if len(statements) != 1:
            _deny("MULTIPLE_STATEMENTS", "只允许一条完整只读查询。")
        tree = statements[0]
        kind = tree.key
        if not isinstance(tree, (exp.Select, exp.Union, exp.Intersect, exp.Except)):
            _deny("STATEMENT_NOT_READ_ONLY", "根节点不是已认证的只读语句。")
        for count, node in enumerate(tree.walk(), 1):
            if count > MAX_AST_NODES:
                _deny("AST_TOO_LARGE", f"SQL 语法树超过 {MAX_AST_NODES} 节点上限。")
            if isinstance(node, exp.Func):
                name = (node.name if isinstance(node, exp.Anonymous) else node.sql_name()).upper()
                if name not in SAFE_FUNCTIONS:
                    _deny("FUNCTION_NOT_ALLOWED", f"函数 {name[:64]} 不在固定允许列表中。")
                functions.add(name)
            elif type(node).__name__ not in SAFE_NODES:
                _deny("NODE_NOT_ALLOWED", f"语法节点 {type(node).__name__} 尚未认证。")
            if isinstance(node, (exp.Union, exp.Intersect, exp.Except)):
                for branch in (node.this, node.expression):
                    if not isinstance(branch, (exp.Select, exp.Union, exp.Intersect, exp.Except, exp.Subquery)):
                        _deny("UNSUPPORTED_SET_BRANCH", "集合查询分支必须是完整 SELECT 子查询。")
            if isinstance(node, exp.With) and node.args.get("recursive"):
                _deny("RECURSIVE_CTE", "不允许递归 CTE。")
            if isinstance(node, exp.Table):
                if not isinstance(node.this, exp.Identifier):
                    _deny("TABLE_FUNCTION_NOT_ALLOWED", "外部文件、网络及其他表函数未获授权。")
                if node.db or node.catalog:
                    _deny("QUALIFIED_CATALOG", "不允许访问当前范围以外的数据库或目录。")
                if any(x in node.name for x in "/\\:."):
                    _deny("PATH_SOURCE_NOT_ALLOWED", "不允许把路径或网络地址作为数据源。")
            if isinstance(node, exp.Join) and (node.args.get("using") or node.args.get("method")):
                _deny("UNSUPPORTED_JOIN", "USING/NATURAL JOIN 尚未认证，请使用明确 ON 条件。")
            if isinstance(node, exp.Star) and any(node.args.values()):
                _deny("UNSUPPORTED_STAR", "带扩展或替换规则的星号尚未认证，请明确字段。")
        tables, columns = _validate_scopes(tree, allowed_tables, table_columns)
        return SQLValidationResult(True, dialect, kind, tables, columns, tuple(sorted(functions)), _tree=tree)
    except _Denied as exc:
        return SQLValidationResult(False, dialect, kind, functions=tuple(sorted(functions)), rejection_code=exc.code, reason=exc.reason)
    except Exception:
        return SQLValidationResult(False, dialect, kind, rejection_code="PARSE_OR_SCOPE_ERROR", reason="SQL 解析或作用域校验失败，请检查方言语法与字段别名。")

def validate_read_query(query: str, allowed_tables: set[str] | None = None, dialect: str = "duckdb",
                        table_columns: Mapping[str, Sequence[str]] | None = None):
    result = validate_sql(query, allowed_tables, dialect, table_columns)
    if not result.allowed:
        raise SQLPolicyError(result)
    return result._tree

def bounded_read_query(query: str, limit: int, *, dialect: str, allowed_tables: set[str],
                       table_columns: Mapping[str, Sequence[str]]) -> str:
    """Keep expressions unchanged; authorize both original and bounded SQL."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100000:
        raise ValueError("取数上限必须是 1 到 100000 之间的整数。")
    validate_read_query(query, allowed_tables, dialect, table_columns)
    try:
        tokens = Dialect.get_or_raise(dialect).tokenize(query)
        # Lexer positions remove only the final separator, not string contents.
        body = query[:tokens[-1].start] if tokens[-1].token_type == TokenType.SEMICOLON else query
        wrapped = f"SELECT * FROM (\n{body}\n) AS __insightpilot_bounded LIMIT {limit + 1}"
        validate_read_query(wrapped, allowed_tables, dialect, table_columns)
        return wrapped
    except SQLPolicyError:
        raise
    except Exception:
        raise ValueError("SQL 限流包装失败，未执行无上限回退。") from None

def redact_sql_values(query: str, dialect: str = "duckdb") -> str:
    tree = validate_read_query(query, dialect=dialect).copy()
    for literal in list(tree.find_all(exp.Literal)):
        literal.replace(exp.Placeholder())
    return tree.sql(dialect=dialect)


def validate_bound_parameters(parameters) -> None:
    """Bindings are scalar values, never SQL fragments or Python objects."""
    from datetime import date, time
    from decimal import Decimal
    from numbers import Number
    if parameters is None:
        return
    if isinstance(parameters, dict):
        if not all(isinstance(key, str) for key in parameters):
            raise ValueError("SQL 参数名称必须是字符串。")
        values = parameters.values()
    elif isinstance(parameters, (list, tuple)):
        values = parameters
    else:
        raise ValueError("SQL 参数必须以列表或字典绑定。")
    if not all(value is None or isinstance(value, (str, bytes, Number, Decimal, date, time)) for value in values):
        raise ValueError("SQL 仅接受标量绑定参数。")
