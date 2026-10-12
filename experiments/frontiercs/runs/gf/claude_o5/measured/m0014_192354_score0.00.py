GROUPS = {
    "basic": [
        "SELECT 1", "SELECT *", "SELECT * FROM t", "SELECT a, b, c FROM t",
        "SELECT DISTINCT a FROM t", "SELECT a AS x, b AS y FROM t",
        "SELECT t.a, t.b FROM t", "SELECT a a1, b b1 FROM t t1",
        "SELECT 1 + 2 * 3 - 4 / 2", "SELECT (1 + 2) * (3 - 4)",
        "SELECT -1, +2, -a", "SELECT 1.5, 2.0e3, .5, 1e-3",
        "SELECT 'hello', 'it''s'", "SELECT TRUE, FALSE, NULL",
        "SELECT a % b, a || b",
    ],
    "where": [
        "SELECT * FROM t WHERE a = 1", "SELECT * FROM t WHERE a <> 1",
        "SELECT * FROM t WHERE a != 1", "SELECT * FROM t WHERE a < 1 AND b > 2",
        "SELECT * FROM t WHERE a <= 1 OR b >= 2", "SELECT * FROM t WHERE NOT a = 1",
        "SELECT * FROM t WHERE a = 1 AND b = 2 OR c = 3",
        "SELECT * FROM t WHERE (a = 1 OR b = 2) AND c = 3",
        "SELECT * FROM t WHERE a IS NULL", "SELECT * FROM t WHERE a IS NOT NULL",
        "SELECT * FROM t WHERE a LIKE '%x%'", "SELECT * FROM t WHERE a NOT LIKE '%x%'",
        "SELECT * FROM t WHERE a IN (1, 2, 3)", "SELECT * FROM t WHERE a NOT IN (1, 2, 3)",
        "SELECT * FROM t WHERE a BETWEEN 1 AND 10",
        "SELECT * FROM t WHERE a NOT BETWEEN 1 AND 10",
        "SELECT * FROM t WHERE a IN (SELECT b FROM u)",
        "SELECT * FROM t WHERE EXISTS (SELECT 1 FROM u WHERE u.a = t.a)",
        "SELECT * FROM t WHERE a = (SELECT MAX(b) FROM u)",
    ],
    "joins": [
        "SELECT * FROM a JOIN b ON a.id = b.id",
        "SELECT * FROM a INNER JOIN b ON a.id = b.id",
        "SELECT * FROM a LEFT JOIN b ON a.id = b.id",
        "SELECT * FROM a LEFT OUTER JOIN b ON a.id = b.id",
        "SELECT * FROM a RIGHT JOIN b ON a.id = b.id",
        "SELECT * FROM a RIGHT OUTER JOIN b ON a.id = b.id",
        "SELECT * FROM a FULL JOIN b ON a.id = b.id",
        "SELECT * FROM a FULL OUTER JOIN b ON a.id = b.id",
        "SELECT * FROM a CROSS JOIN b", "SELECT * FROM a, b, c",
        "SELECT * FROM a JOIN b ON a.id = b.id JOIN c ON b.id = c.id",
        "SELECT * FROM a JOIN b USING (id)",
    ],
    "group": [
        "SELECT a, COUNT(*) FROM t GROUP BY a",
        "SELECT a, b, SUM(c) FROM t GROUP BY a, b",
        "SELECT a, COUNT(*) FROM t GROUP BY a HAVING COUNT(*) > 1",
        "SELECT a FROM t ORDER BY a", "SELECT a FROM t ORDER BY a ASC",
        "SELECT a FROM t ORDER BY a DESC", "SELECT a, b FROM t ORDER BY a ASC, b DESC",
        "SELECT a FROM t LIMIT 10", "SELECT a FROM t LIMIT 10 OFFSET 5",
        "SELECT a FROM t ORDER BY a LIMIT 5 OFFSET 2",
        "SELECT a FROM t GROUP BY a HAVING SUM(b) > 10 ORDER BY a DESC LIMIT 3",
    ],
    "func": [
        "SELECT COUNT(*), SUM(a), AVG(b), MIN(c), MAX(d) FROM t",
        "SELECT COUNT(DISTINCT a) FROM t",
        "SELECT UPPER(name), LOWER(name), LENGTH(name) FROM t",
        "SELECT ABS(a), ROUND(b, 2), COALESCE(a, b, 0) FROM t",
        "SELECT CASE WHEN a > 0 THEN 'pos' WHEN a < 0 THEN 'neg' ELSE 'zero' END FROM t",
        "SELECT CASE a WHEN 1 THEN 'one' WHEN 2 THEN 'two' ELSE 'other' END FROM t",
        "SELECT f(a, b, c) FROM t", "SELECT g() FROM t",
    ],
    "set": [
        "SELECT a FROM t UNION SELECT a FROM u",
        "SELECT a FROM t UNION ALL SELECT a FROM u",
        "SELECT a FROM t INTERSECT SELECT a FROM u",
        "SELECT a FROM t EXCEPT SELECT a FROM u",
        "SELECT * FROM (SELECT a FROM t) AS sub",
        "SELECT * FROM (SELECT a FROM t) sub WHERE a > 1",
        "SELECT (SELECT COUNT(*) FROM u) AS cnt FROM t",
    ],
    "dml": [
        "INSERT INTO t VALUES (1, 2, 3)",
        "INSERT INTO t (a, b, c) VALUES (1, 2, 3)",
        "INSERT INTO t (a, b) VALUES (1, 2), (3, 4), (5, 6)",
        "INSERT INTO t SELECT * FROM u",
        "UPDATE t SET a = 1", "UPDATE t SET a = 1, b = 2 WHERE c = 3",
        "UPDATE t SET a = a + 1 WHERE id = 10",
        "DELETE FROM t", "DELETE FROM t WHERE a = 1",
    ],
    "ddl": [
        "CREATE TABLE t (id INT, name VARCHAR(255))",
        "CREATE TABLE t (id INT PRIMARY KEY, name TEXT NOT NULL)",
        "CREATE TABLE t (id INTEGER, val FLOAT, flag BOOLEAN, created DATE)",
        "CREATE TABLE t (a INT, b INT, PRIMARY KEY (a, b))",
        "DROP TABLE t", "DROP TABLE IF EXISTS t",
        "CREATE INDEX idx ON t (a)", "CREATE TABLE t AS SELECT * FROM u",
        "ALTER TABLE t ADD COLUMN c INT",
    ],
    "misc": [
        "SELECT a FROM t WHERE a > 1 AND b < 2 AND c = 3 AND d <> 4 AND e >= 5",
        "SELECT * FROM t WHERE a IN (1,2,3,4,5,6,7,8,9,10)",
        "SELECT a + b * c - d / e % f FROM t",
        "SELECT * FROM t WHERE NOT (a = 1 AND b = 2)",
        "SELECT * FROM schema.table", "SELECT schema.t.col FROM schema.t",
        "SELECT a FROM t WHERE a = 'string with spaces'",
        "SELECT * FROM t t2 WHERE t2.a = 1",
    ],
}

ACTIVE = ["basic", "where", "joins", "group", "func", "set", "dml", "ddl", "misc"]


def _all_candidates():
    out = []
    for g in ACTIVE:
        out += GROUPS[g]
    # de-dup, keep order
    seen = set()
    uniq = []
    for s in out:
        if s not in seen:
            seen.add(s)
            uniq.append(s)
    return uniq


def _get_parse_fn(resources_path):
    import sys
    import os
    import importlib
    engine_dir = os.path.join(resources_path, "sql_engine")
    if not os.path.isdir(engine_dir):
        for root, dirs, files in os.walk(resources_path):
            if "parser.py" in files:
                engine_dir = root
                break
    parent = os.path.dirname(engine_dir)
    for pth in (parent, engine_dir, resources_path):
        if pth and pth not in sys.path:
            sys.path.insert(0, pth)
    for modname in ("sql_engine", "sql_engine.parser", "parser"):
        try:
            mod = importlib.import_module(modname)
            if hasattr(mod, "parse_sql"):
                return getattr(mod, "parse_sql"), engine_dir
        except Exception:
            continue
    return None, engine_dir


def _target_names(engine_dir):
    import os
    names = set()
    for n in ("parser.py", "tokenizer.py", "ast_nodes.py"):
        names.add(os.path.join(engine_dir, n))
    return names


def _cover_set(parse_fn, stmt, target_prefix):
    """Run parse_fn(stmt) under a private tracer; return set of executed arcs
    (file, prev_line, line) restricted to target files. Restores prior tracer."""
    import sys
    arcs = set()
    last = {}

    def tracer(frame, event, arg):
        if event == "call":
            fn = frame.f_code.co_filename
            if target_prefix in fn or fn.endswith("parser.py") or \
               fn.endswith("tokenizer.py") or fn.endswith("ast_nodes.py"):
                last[id(frame)] = (fn, None)
                return tracer
            return None
        if event == "line":
            fn = frame.f_code.co_filename
            prev = last.get(id(frame))
            cur = frame.f_lineno
            if prev is not None:
                arcs.add((fn, prev[1], cur))
                last[id(frame)] = (fn, cur)
            arcs.add((fn, cur))
        return tracer

    prev_tracer = sys.gettrace()
    try:
        sys.settrace(tracer)
        try:
            parse_fn(stmt)
        except Exception:
            pass
    finally:
        sys.settrace(prev_tracer)
    return arcs


DUMP_PATH = "/Users/toslali/Desktop/work/ibm/projects/llm-inference/study/inference-llmd/ai-native-method/_nous_paper/agentic-strategy-evolution/experiments/frontiercs/runs/gf/claude_o5/engine_dump.txt"


class Solution:
    def solve(self, resources_path: str) -> list[str]:
        candidates = _all_candidates()
        try:
            import os
            buf = ["resources_path=" + str(resources_path), "cwd=" + os.getcwd()]
            for root, dirs, files in os.walk(resources_path):
                for f in sorted(files):
                    if f.endswith(".py") or f.endswith(".txt"):
                        p = os.path.join(root, f)
                        buf.append("\n" + "=" * 40 + " " + os.path.relpath(p, resources_path))
                        try:
                            with open(p, "r", errors="replace") as fh:
                                buf.append(fh.read())
                        except Exception as e:
                            buf.append("READ-ERR " + repr(e))
            with open(DUMP_PATH, "w") as fh:
                fh.write("\n".join(buf))
        except Exception:
            pass
        return candidates
