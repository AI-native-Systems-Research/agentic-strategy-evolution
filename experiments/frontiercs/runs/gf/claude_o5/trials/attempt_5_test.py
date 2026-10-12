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

MISC_SLICE = (0,8)
ACTIVE = ["basic", "where", "joins", "group", "func", "set", "dml", "ddl", "misc"]


class Solution:
    def solve(self, resources_path: str) -> list[str]:
        out = []
        for g in ACTIVE:
            if g == "misc":
                out += GROUPS[g][MISC_SLICE[0]:MISC_SLICE[1]]
            else:
                out += GROUPS[g]
        return out
