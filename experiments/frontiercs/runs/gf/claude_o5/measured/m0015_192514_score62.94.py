LEAN = [
    # literals, expressions, aliases, star, distinct, dotted names
    "SELECT 1",
    "SELECT *",
    "SELECT DISTINCT a AS x, t.b b1, 1 + 2 * 3 - 4 / 2, -a, +b, 'it''s', TRUE, FALSE, NULL FROM t t1",
    "SELECT 1.5, 2.0e3, .5, 1e-3, a % b, a || b FROM t",
    "SELECT schema.t.col FROM schema.t",
    "SELECT (1 + 2) * (3 - 4)",
    # where / operators
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
    # joins (chain many kinds) + using + comma
    "SELECT * FROM a INNER JOIN b ON a.id = b.id LEFT OUTER JOIN c ON b.id = c.id RIGHT OUTER JOIN d ON c.id = d.id FULL OUTER JOIN e ON d.id = e.id CROSS JOIN f",
    "SELECT * FROM a JOIN b ON a.id = b.id LEFT JOIN c ON b.id = c.id RIGHT JOIN d ON c.id = d.id FULL JOIN e ON d.id = e.id",
    "SELECT * FROM a JOIN b USING (id)",
    "SELECT * FROM a, b, c",
    # group / having / order / limit / offset
    "SELECT a, b, COUNT(*) FROM t GROUP BY a, b HAVING COUNT(*) > 1 ORDER BY a ASC, b DESC LIMIT 5 OFFSET 2",
    # aggregates / functions / case
    "SELECT COUNT(*), SUM(a), AVG(b), MIN(c), MAX(d), COUNT(DISTINCT a) FROM t",
    "SELECT UPPER(name), LOWER(name), LENGTH(name), ABS(a), ROUND(b, 2), COALESCE(a, b, 0), f(a, b, c), g() FROM t",
    "SELECT CASE WHEN a > 0 THEN 'pos' WHEN a < 0 THEN 'neg' ELSE 'zero' END FROM t",
    "SELECT CASE a WHEN 1 THEN 'one' WHEN 2 THEN 'two' ELSE 'other' END FROM t",
    # set ops
    "SELECT a FROM t UNION SELECT a FROM u",
    "SELECT a FROM t UNION ALL SELECT a FROM u",
    "SELECT a FROM t INTERSECT SELECT a FROM u",
    "SELECT a FROM t EXCEPT SELECT a FROM u",
    # subqueries
    "SELECT * FROM (SELECT a FROM t) AS sub WHERE a > 1",
    "SELECT (SELECT COUNT(*) FROM u) AS cnt FROM t",
    # DML
    "INSERT INTO t (a, b, c) VALUES (1, 2, 3), (4, 5, 6)",
    "INSERT INTO t VALUES (1, 2, 3)",
    "INSERT INTO t SELECT * FROM u",
    "UPDATE t SET a = a + 1, b = 2 WHERE c = 3",
    "DELETE FROM t WHERE a = 1",
    "DELETE FROM t",
    # DDL
    "CREATE TABLE t (id INT PRIMARY KEY, name VARCHAR(255) NOT NULL, val FLOAT, flag BOOLEAN, created DATE, PRIMARY KEY (id, name))",
    "DROP TABLE IF EXISTS t",
    "DROP TABLE t",
    "CREATE INDEX idx ON t (a)",
    "CREATE TABLE t AS SELECT * FROM u",
    "ALTER TABLE t ADD COLUMN c INT",
]


class Solution:
    def solve(self, resources_path: str) -> list[str]:
        return list(LEAN)
