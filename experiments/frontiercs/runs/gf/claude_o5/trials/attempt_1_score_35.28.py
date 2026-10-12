import os
import sys
import re
import importlib


def _candidate_pool(resources_path):
    """A broad, diverse pool of SQL statements covering many parser paths."""
    pool = []

    # Basic selects
    pool += [
        "SELECT 1",
        "SELECT *",
        "SELECT * FROM t",
        "SELECT a, b, c FROM t",
        "SELECT DISTINCT a FROM t",
        "SELECT a AS x, b AS y FROM t",
        "SELECT t.a, t.b FROM t",
        "SELECT a a1, b b1 FROM t t1",
        "SELECT 1 + 2 * 3 - 4 / 2",
        "SELECT (1 + 2) * (3 - 4)",
        "SELECT -1, +2, -a",
        "SELECT 1.5, 2.0e3, .5, 1e-3",
        "SELECT 'hello', 'it''s'",
        "SELECT TRUE, FALSE, NULL",
        "SELECT a % b, a || b",
    ]

    # Where clauses and operators
    pool += [
        "SELECT * FROM t WHERE a = 1",
        "SELECT * FROM t WHERE a <> 1",
        "SELECT * FROM t WHERE a != 1",
        "SELECT * FROM t WHERE a < 1 AND b > 2",
        "SELECT * FROM t WHERE a <= 1 OR b >= 2",
        "SELECT * FROM t WHERE NOT a = 1",
        "SELECT * FROM t WHERE a = 1 AND b = 2 OR c = 3",
        "SELECT * FROM t WHERE (a = 1 OR b = 2) AND c = 3",
        "SELECT * FROM t WHERE a IS NULL",
        "SELECT * FROM t WHERE a IS NOT NULL",
        "SELECT * FROM t WHERE a LIKE '%x%'",
        "SELECT * FROM t WHERE a NOT LIKE '%x%'",
        "SELECT * FROM t WHERE a IN (1, 2, 3)",
        "SELECT * FROM t WHERE a NOT IN (1, 2, 3)",
        "SELECT * FROM t WHERE a BETWEEN 1 AND 10",
        "SELECT * FROM t WHERE a NOT BETWEEN 1 AND 10",
        "SELECT * FROM t WHERE a IN (SELECT b FROM u)",
        "SELECT * FROM t WHERE EXISTS (SELECT 1 FROM u WHERE u.a = t.a)",
        "SELECT * FROM t WHERE a = (SELECT MAX(b) FROM u)",
    ]

    # Joins
    pool += [
        "SELECT * FROM a JOIN b ON a.id = b.id",
        "SELECT * FROM a INNER JOIN b ON a.id = b.id",
        "SELECT * FROM a LEFT JOIN b ON a.id = b.id",
        "SELECT * FROM a LEFT OUTER JOIN b ON a.id = b.id",
        "SELECT * FROM a RIGHT JOIN b ON a.id = b.id",
        "SELECT * FROM a RIGHT OUTER JOIN b ON a.id = b.id",
        "SELECT * FROM a FULL JOIN b ON a.id = b.id",
        "SELECT * FROM a FULL OUTER JOIN b ON a.id = b.id",
        "SELECT * FROM a CROSS JOIN b",
        "SELECT * FROM a, b, c",
        "SELECT * FROM a JOIN b ON a.id = b.id JOIN c ON b.id = c.id",
        "SELECT * FROM a JOIN b USING (id)",
    ]

    # Group / having / order / limit
    pool += [
        "SELECT a, COUNT(*) FROM t GROUP BY a",
        "SELECT a, b, SUM(c) FROM t GROUP BY a, b",
        "SELECT a, COUNT(*) FROM t GROUP BY a HAVING COUNT(*) > 1",
        "SELECT a FROM t ORDER BY a",
        "SELECT a FROM t ORDER BY a ASC",
        "SELECT a FROM t ORDER BY a DESC",
        "SELECT a, b FROM t ORDER BY a ASC, b DESC",
        "SELECT a FROM t LIMIT 10",
        "SELECT a FROM t LIMIT 10 OFFSET 5",
        "SELECT a FROM t ORDER BY a LIMIT 5 OFFSET 2",
        "SELECT a FROM t GROUP BY a HAVING SUM(b) > 10 ORDER BY a DESC LIMIT 3",
    ]

    # Functions, aggregates, case
    pool += [
        "SELECT COUNT(*), SUM(a), AVG(b), MIN(c), MAX(d) FROM t",
        "SELECT COUNT(DISTINCT a) FROM t",
        "SELECT UPPER(name), LOWER(name), LENGTH(name) FROM t",
        "SELECT ABS(a), ROUND(b, 2), COALESCE(a, b, 0) FROM t",
        "SELECT CASE WHEN a > 0 THEN 'pos' WHEN a < 0 THEN 'neg' ELSE 'zero' END FROM t",
        "SELECT CASE a WHEN 1 THEN 'one' WHEN 2 THEN 'two' ELSE 'other' END FROM t",
        "SELECT f(a, b, c) FROM t",
        "SELECT g() FROM t",
    ]

    # Set operations and subqueries
    pool += [
        "SELECT a FROM t UNION SELECT a FROM u",
        "SELECT a FROM t UNION ALL SELECT a FROM u",
        "SELECT a FROM t INTERSECT SELECT a FROM u",
        "SELECT a FROM t EXCEPT SELECT a FROM u",
        "SELECT * FROM (SELECT a FROM t) AS sub",
        "SELECT * FROM (SELECT a FROM t) sub WHERE a > 1",
        "SELECT (SELECT COUNT(*) FROM u) AS cnt FROM t",
    ]

    # DML
    pool += [
        "INSERT INTO t VALUES (1, 2, 3)",
        "INSERT INTO t (a, b, c) VALUES (1, 2, 3)",
        "INSERT INTO t (a, b) VALUES (1, 2), (3, 4), (5, 6)",
        "INSERT INTO t SELECT * FROM u",
        "UPDATE t SET a = 1",
        "UPDATE t SET a = 1, b = 2 WHERE c = 3",
        "UPDATE t SET a = a + 1 WHERE id = 10",
        "DELETE FROM t",
        "DELETE FROM t WHERE a = 1",
    ]

    # DDL
    pool += [
        "CREATE TABLE t (id INT, name VARCHAR(255))",
        "CREATE TABLE t (id INT PRIMARY KEY, name TEXT NOT NULL)",
        "CREATE TABLE t (id INTEGER, val FLOAT, flag BOOLEAN, created DATE)",
        "CREATE TABLE t (a INT, b INT, PRIMARY KEY (a, b))",
        "DROP TABLE t",
        "DROP TABLE IF EXISTS t",
        "CREATE INDEX idx ON t (a)",
        "CREATE TABLE t AS SELECT * FROM u",
        "ALTER TABLE t ADD COLUMN c INT",
    ]

    # Misc / stress
    pool += [
        "SELECT a FROM t WHERE a > 1 AND b < 2 AND c = 3 AND d <> 4 AND e >= 5",
        "SELECT * FROM t WHERE a IN (1,2,3,4,5,6,7,8,9,10)",
        "SELECT a + b * c - d / e % f FROM t",
        "SELECT * FROM t WHERE NOT (a = 1 AND b = 2)",
        "SELECT * FROM schema.table",
        "SELECT schema.t.col FROM schema.t",
        "SELECT a FROM t WHERE a = 'string with spaces'",
        "SELECT * FROM t t2 WHERE t2.a = 1",
    ]

    # Augment with keyword-driven extras from source (best-effort, generic)
    return pool


def _target_files(engine_dir):
    out = []
    for name in ("parser.py", "tokenizer.py", "ast_nodes.py"):
        p = os.path.join(engine_dir, name)
        if os.path.exists(p):
            out.append(os.path.abspath(p))
    if not out:
        for root, _, files in os.walk(engine_dir):
            for f in files:
                if f.endswith(".py"):
                    out.append(os.path.abspath(os.path.join(root, f)))
    return out


def _get_parser(resources_path):
    engine_dir = os.path.join(resources_path, "sql_engine")
    if not os.path.isdir(engine_dir):
        for root, dirs, files in os.walk(resources_path):
            if "parser.py" in files:
                engine_dir = root
                break
    # Make the package importable
    parent = os.path.dirname(engine_dir)
    for pth in (parent, engine_dir, resources_path):
        if pth and pth not in sys.path:
            sys.path.insert(0, pth)
    parse_fn = None
    for modname in ("sql_engine", "sql_engine.parser", "parser"):
        try:
            mod = importlib.import_module(modname)
            if hasattr(mod, "parse_sql"):
                parse_fn = getattr(mod, "parse_sql")
                break
        except Exception:
            continue
    return parse_fn, engine_dir


def _greedy_select(candidates, parse_fn, targets):
    try:
        import coverage
    except Exception:
        # No coverage available: just return everything that parses
        good = []
        for s in candidates:
            try:
                parse_fn(s)
                good.append(s)
            except Exception:
                pass
        return good

    targetset = set(targets)
    cover_sets = []  # (stmt, frozenset of (file,lineno) and arcs)
    for s in candidates:
        cov = coverage.Coverage(branch=True)
        cov.start()
        try:
            parse_fn(s)
        except Exception:
            cov.stop()
            continue
        cov.stop()
        data = cov.get_data()
        items = set()
        for f in data.measured_files():
            af = os.path.abspath(f)
            if af not in targetset:
                continue
            lines = data.lines(f) or []
            for ln in lines:
                items.add((af, ln))
            try:
                arcs = data.arcs(f) or []
                for arc in arcs:
                    items.add((af, arc))
            except Exception:
                pass
        if items:
            cover_sets.append((s, frozenset(items)))

    # Greedy set cover: keep adding the statement that yields the most new items.
    selected = []
    covered = set()
    remaining = list(cover_sets)
    while remaining:
        best_i = -1
        best_gain = 0
        for i, (s, items) in enumerate(remaining):
            gain = len(items - covered)
            if gain > best_gain:
                best_gain = gain
                best_i = i
        if best_i < 0 or best_gain <= 0:
            break
        s, items = remaining.pop(best_i)
        selected.append(s)
        covered |= items
    return selected


class Solution:
    def solve(self, resources_path: str) -> list[str]:
        pool = _candidate_pool(resources_path)
        try:
            parse_fn, engine_dir = _get_parser(resources_path)
        except Exception:
            parse_fn, engine_dir = None, os.path.join(resources_path, "sql_engine")

        if parse_fn is None:
            return pool

        # Keep only statements that actually parse (invalid ones add no coverage).
        selected = []
        for s in pool:
            try:
                parse_fn(s)
                selected.append(s)
            except Exception:
                pass
        if not selected:
            selected = pool
        return selected
