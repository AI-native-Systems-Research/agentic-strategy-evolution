import os
import sys
import json
import subprocess

LEAN = [
    "SELECT *",
    "SELECT DISTINCT a AS x, t.b b1, 1 + 2 * 3 - 4 / 2, -a, +b, 'it''s', TRUE, FALSE, NULL FROM t t1",
    "SELECT 1.5, 2.0e3, .5, 1e-3, a % b, a || b FROM t",
    "SELECT schema.t.col FROM schema.t",
    "SELECT * FROM t WHERE a = 1 AND b <> 2 OR NOT c < 3",
    "SELECT * FROM t WHERE a <= 1 AND b >= 2 AND c != 4 AND d > 5",
    "SELECT * FROM t WHERE a IS NULL OR b IS NOT NULL",
    "SELECT * FROM t WHERE a LIKE '%x%' AND b NOT LIKE 'y_'",
    "SELECT * FROM t WHERE a IN (1, 2, 3) AND b NOT IN (4, 5)",
    "SELECT * FROM t WHERE a BETWEEN 1 AND 10 AND b NOT BETWEEN 2 AND 3",
    "SELECT * FROM t WHERE a IN (SELECT b FROM u)",
    "SELECT * FROM t WHERE EXISTS (SELECT 1 FROM u WHERE u.a = t.a)",
    "SELECT * FROM t WHERE a = (SELECT MAX(b) FROM u)",
    "SELECT * FROM t WHERE NOT (a = 1 AND b = 2)",
    "SELECT * FROM a INNER JOIN b ON a.id = b.id LEFT OUTER JOIN c ON b.id = c.id RIGHT OUTER JOIN d ON c.id = d.id FULL OUTER JOIN e ON d.id = e.id CROSS JOIN f",
    "SELECT * FROM a JOIN b ON a.id = b.id LEFT JOIN c ON b.id = c.id RIGHT JOIN d ON c.id = d.id FULL JOIN e ON d.id = e.id",
    "SELECT * FROM a JOIN b USING (id)",
    "SELECT * FROM a, b, c",
    "SELECT a, b, COUNT(*) FROM t GROUP BY a, b HAVING COUNT(*) > 1 ORDER BY a ASC, b DESC LIMIT 5 OFFSET 2",
    "SELECT COUNT(*), SUM(a), AVG(b), MIN(c), MAX(d), COUNT(DISTINCT a) FROM t",
    "SELECT UPPER(name), LOWER(name), LENGTH(name), ABS(a), ROUND(b, 2), COALESCE(a, b, 0), f(a, b, c), g() FROM t",
    "SELECT CASE WHEN a > 0 THEN 'pos' WHEN a < 0 THEN 'neg' ELSE 'zero' END FROM t",
    "SELECT CASE a WHEN 1 THEN 'one' WHEN 2 THEN 'two' ELSE 'other' END FROM t",
    "SELECT a FROM t UNION SELECT a FROM u",
    "SELECT a FROM t UNION ALL SELECT a FROM u",
    "SELECT a FROM t INTERSECT SELECT a FROM u",
    "SELECT a FROM t EXCEPT SELECT a FROM u",
    "SELECT * FROM (SELECT a FROM t) AS sub WHERE a > 1",
    "SELECT (SELECT COUNT(*) FROM u) AS cnt FROM t",
    "INSERT INTO t (a, b, c) VALUES (1, 2, 3), (4, 5, 6)",
    "INSERT INTO t VALUES (1, 2, 3)",
    "INSERT INTO t SELECT * FROM u",
    "UPDATE t SET a = a + 1, b = 2 WHERE c = 3",
    "DELETE FROM t WHERE a = 1",
    "DELETE FROM t",
    "CREATE TABLE t (id INT PRIMARY KEY, name VARCHAR(255) NOT NULL, val FLOAT, flag BOOLEAN, created DATE, PRIMARY KEY (id, name))",
    "DROP TABLE IF EXISTS t",
    "DROP TABLE t",
    "CREATE INDEX idx ON t (a)",
    "CREATE TABLE t AS SELECT * FROM u",
    "ALTER TABLE t ADD COLUMN c INT",
]

# Extra candidates to broaden the search pool for the optimizer.
EXTRA = [
    "SELECT 1",
    "SELECT (1 + 2) * (3 - 4) / 5 % 6",
    "SELECT a AS x, b y, t.c, 1, 'str', NULL, TRUE, FALSE FROM t",
    "SELECT a a1 FROM t t1",
    "SELECT * FROM t WHERE a > 1 AND b < 2 AND c = 3 AND d <> 4 AND e >= 5 AND f <= 6",
    "SELECT * FROM t WHERE NOT a = 1",
    "SELECT * FROM t WHERE a IS NOT NULL",
    "SELECT * FROM t WHERE a NOT LIKE '%x%'",
    "SELECT * FROM t WHERE a NOT IN (1, 2, 3)",
    "SELECT * FROM t WHERE a NOT BETWEEN 1 AND 10",
    "SELECT * FROM t WHERE a NOT IN (SELECT b FROM u)",
    "SELECT * FROM t WHERE NOT EXISTS (SELECT 1 FROM u)",
    "SELECT a + b * c - d / e % f || g FROM t",
    "SELECT a FROM t ORDER BY a",
    "SELECT a FROM t ORDER BY a DESC",
    "SELECT a FROM t ORDER BY a ASC, b DESC",
    "SELECT a FROM t LIMIT 10",
    "SELECT a FROM t LIMIT 10 OFFSET 5",
    "SELECT a FROM t GROUP BY a",
    "SELECT a FROM t GROUP BY a HAVING COUNT(*) > 1",
    "SELECT a, COUNT(*) FROM t GROUP BY a",
    "SELECT COUNT(DISTINCT a) FROM t",
    "SELECT MIN(a), MAX(b) FROM t",
    "SELECT f(a), g(b, c), h() FROM t",
    "SELECT CASE WHEN a > 0 THEN 1 ELSE 0 END FROM t",
    "SELECT CASE a WHEN 1 THEN 'x' END FROM t",
    "SELECT a FROM t UNION SELECT a FROM u UNION ALL SELECT a FROM v",
    "SELECT a FROM t INTERSECT SELECT a FROM u EXCEPT SELECT a FROM v",
    "SELECT * FROM (SELECT a, b FROM t WHERE a > 1) sub",
    "SELECT * FROM (SELECT a FROM t) x JOIN (SELECT b FROM u) y ON x.a = y.b",
    "INSERT INTO t (a) VALUES (1)",
    "INSERT INTO t VALUES (1, 2), (3, 4)",
    "UPDATE t SET a = 1",
    "UPDATE t SET a = 1, b = 2, c = 3 WHERE id = 10",
    "CREATE TABLE t (id INT, name TEXT)",
    "CREATE TABLE t (a INT, b INT, PRIMARY KEY (a, b))",
    "DROP INDEX idx",
    "SELECT * FROM a INNER JOIN b ON a.id = b.id",
    "SELECT * FROM a LEFT JOIN b ON a.id = b.id",
    "SELECT * FROM a RIGHT JOIN b ON a.id = b.id",
    "SELECT * FROM a FULL JOIN b ON a.id = b.id",
    "SELECT * FROM a CROSS JOIN b",
    "SELECT t.* FROM t",
    "SELECT ALL a FROM t",
    "SELECT * FROM t WHERE a = 'string with spaces'",
    "SELECT * FROM t AS x WHERE x.a = 1",
]


CHILD = r'''
import sys, os, json

def main():
    resources_path = sys.argv[1]
    candidates = json.loads(sys.argv[2])

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

    import importlib
    parse_fn = None
    for modname in ("sql_engine", "sql_engine.parser", "parser"):
        try:
            mod = importlib.import_module(modname)
            if hasattr(mod, "parse_sql"):
                parse_fn = getattr(mod, "parse_sql")
                break
        except Exception:
            continue
    if parse_fn is None:
        print(json.dumps({"ok": False}))
        return

    tnames = ("parser.py", "tokenizer.py", "ast_nodes.py")
    target_files = {}
    for n in tnames:
        p = os.path.abspath(os.path.join(engine_dir, n))
        if os.path.exists(p):
            target_files[p] = True

    # Denominators via static analysis of the source files.
    total_lines = 0
    total_arcs = 0
    try:
        from coverage.parser import PythonParser
        for f in target_files:
            try:
                pp = PythonParser(filename=f)
                pp.parse_source()
                total_lines += len(pp.statements)
                try:
                    total_arcs += len(pp.arcs())
                except Exception:
                    pass
            except Exception:
                pass
    except Exception:
        pass

    def measure(stmt):
        lines = set()
        arcs = set()
        last = {}
        def tracer(frame, event, arg):
            fn = frame.f_code.co_filename
            afn = os.path.abspath(fn)
            if afn not in target_files:
                return None
            if event == "call":
                last[id(frame)] = -1
                return tracer
            if event == "line":
                cur = frame.f_lineno
                lines.add((afn, cur))
                prev = last.get(id(frame), -1)
                arcs.add((afn, prev, cur))
                last[id(frame)] = cur
            elif event == "return":
                prev = last.get(id(frame), -1)
                arcs.add((afn, prev, frame.f_lineno))
            return tracer
        sys.settrace(tracer)
        try:
            parse_fn(stmt)
            ok = True
        except Exception:
            ok = False
        finally:
            sys.settrace(None)
        return lines, arcs, ok

    data = []
    for s in candidates:
        lines, arcs, ok = measure(s)
        if ok and (lines or arcs):
            data.append((s, lines, arcs))

    # Greedy order by marginal (lines + arcs) gain.
    order = []
    cov_lines = set()
    cov_arcs = set()
    remaining = list(range(len(data)))
    while remaining:
        best_i = -1
        best_gain = 0
        for i in remaining:
            s, l, a = data[i]
            gain = len(l - cov_lines) + len(a - cov_arcs)
            if gain > best_gain:
                best_gain = gain
                best_i = i
        if best_i < 0 or best_gain <= 0:
            break
        remaining.remove(best_i)
        s, l, a = data[best_i]
        order.append(best_i)
        cov_lines |= l
        cov_arcs |= a

    # Compute score along the greedy prefix; pick the best prefix.
    def score_for(nlines, narcs, N):
        if total_lines <= 0 or total_arcs <= 0:
            return -1
        lc = nlines / total_lines * 100.0
        bc = narcs / total_arcs * 100.0
        w = 0.6 * lc + 0.4 * bc
        adj = (w / 100.0) ** 3 * 100.0
        return 0.7 * adj + 30.0 * (2.0 ** (-N / 50.0))

    best_prefix = len(order)
    if total_lines > 0 and total_arcs > 0:
        cl = set()
        ca = set()
        best_score = -1
        best_prefix = 0
        for k, idx in enumerate(order, start=1):
            s, l, a = data[idx]
            cl |= l
            ca |= a
            sc = score_for(len(cl), len(ca), k)
            if sc >= best_score:
                best_score = sc
                best_prefix = k
    selected = [data[idx][0] for idx in order[:best_prefix]]

    print(json.dumps({
        "ok": True,
        "selected": selected,
        "total_lines": total_lines,
        "total_arcs": total_arcs,
        "ncand": len(data),
    }))

main()
'''


class Solution:
    def solve(self, resources_path: str) -> list[str]:
        pool = list(dict.fromkeys(LEAN + EXTRA))
        try:
            res = subprocess.run(
                [sys.executable, "-c", CHILD, resources_path, json.dumps(pool)],
                capture_output=True, text=True, timeout=120,
            )
            out = res.stdout.strip().splitlines()
            if out:
                info = json.loads(out[-1])
                if info.get("ok") and info.get("selected"):
                    return info["selected"]
        except Exception:
            pass
        return list(LEAN)
