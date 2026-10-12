class Solution:
    def solve(self, resources_path: str) -> list[str]:
        """Minimal high-impact test set for maximum efficiency bonus."""

        return [
            # Core statement types with maximum branch coverage each
            "SELECT * FROM t",
            "SELECT a, b FROM t WHERE c = 1 AND d > 2 OR e < 3",
            "SELECT DISTINCT a, COUNT(*), SUM(b), AVG(c), MIN(d), MAX(e) FROM t GROUP BY a HAVING COUNT(*) > 1 ORDER BY a DESC LIMIT 10",

            # All JOIN types
            "SELECT * FROM t1 JOIN t2 ON t1.id = t2.id",
            "SELECT * FROM t1 LEFT JOIN t2 ON t1.id = t2.id",
            "SELECT * FROM t1 RIGHT JOIN t2 ON t1.id = t2.id",
            "SELECT * FROM t1 FULL OUTER JOIN t2 ON t1.id = t2.id",
            "SELECT * FROM t1 CROSS JOIN t2",
            "SELECT * FROM t1 NATURAL JOIN t2",

            # Subqueries in all positions
            "SELECT * FROM (SELECT a FROM t WHERE b IN (SELECT c FROM t2)) AS sub WHERE a = (SELECT MAX(d) FROM t3)",
            "SELECT a, (SELECT COUNT(*) FROM t2 WHERE t2.x = t1.x) FROM t1 WHERE EXISTS (SELECT 1 FROM t3)",

            # Set operations
            "SELECT a FROM t1 UNION SELECT a FROM t2",
            "SELECT a FROM t1 UNION ALL SELECT a FROM t2",
            "SELECT a FROM t1 INTERSECT SELECT a FROM t2",
            "SELECT a FROM t1 EXCEPT SELECT a FROM t2",

            # DML with all features
            "INSERT INTO t (a, b) VALUES (1, 2), (3, 4)",
            "INSERT INTO t SELECT * FROM t2",
            "UPDATE t SET a = 1, b = b + 1 WHERE c IN (SELECT d FROM t2)",
            "DELETE FROM t WHERE a = 1",

            # DDL
            "CREATE TABLE t (id INT PRIMARY KEY, name VARCHAR(100) NOT NULL, price DECIMAL(10,2) DEFAULT 0)",
            "CREATE TABLE IF NOT EXISTS t2 (a INT)",
            "DROP TABLE IF EXISTS t",
            "ALTER TABLE t ADD COLUMN x INT",
            "ALTER TABLE t DROP COLUMN x",
            "CREATE INDEX idx ON t(a, b)",
            "DROP INDEX idx",
            "CREATE VIEW v AS SELECT * FROM t WHERE a > 0",
            "DROP VIEW v",
            "TRUNCATE TABLE t",

            # All expression types and operators
            "SELECT 1, -2, 3.14, -5.5, 1e10, 'string', '', 'can''t', NULL, TRUE, FALSE",
            "SELECT a + b, c - d, e * f, g / h, i % j, -k, (l + m) * n FROM t",
            "SELECT a = b, c <> d, e != f, g < h, i <= j, k > l, m >= n FROM t",
            "SELECT a AND b, c OR d, NOT e, (f OR g) AND h FROM t",
            "SELECT * FROM t WHERE a IS NULL OR b IS NOT NULL OR c LIKE 'd%' OR e NOT LIKE 'f%' OR g IN (1,2,3) OR h NOT IN (4,5) OR i BETWEEN 1 AND 10 OR j NOT BETWEEN 11 AND 20",

            # CASE and conditionals
            "SELECT CASE WHEN a > 0 THEN 1 WHEN a < 0 THEN -1 ELSE 0 END, CASE b WHEN 'x' THEN 1 WHEN 'y' THEN 2 ELSE 3 END FROM t",

            # All major functions
            "SELECT UPPER(a), LOWER(b), LENGTH(c), TRIM(d), LTRIM(e), RTRIM(f), SUBSTRING(g, 1, 10), CONCAT(h, i) FROM t",
            "SELECT COALESCE(a, b, 0), NULLIF(c, 0), ABS(d), ROUND(e, 2), FLOOR(f), CEIL(g), SQRT(h), POWER(i, 2) FROM t",
            "SELECT NOW(), CURRENT_DATE, CURRENT_TIME, CURRENT_TIMESTAMP, EXTRACT(YEAR FROM d), EXTRACT(MONTH FROM d), EXTRACT(DAY FROM d) FROM t",

            # Window functions
            "SELECT ROW_NUMBER() OVER (PARTITION BY a ORDER BY b), RANK() OVER (ORDER BY c), DENSE_RANK() OVER (ORDER BY d) FROM t",
            "SELECT SUM(a) OVER (ORDER BY b), AVG(c) OVER (PARTITION BY d), LAG(e) OVER (ORDER BY f), LEAD(g) OVER (ORDER BY h) FROM t",
            "SELECT FIRST_VALUE(a) OVER (ORDER BY b), LAST_VALUE(c) OVER (ORDER BY d), COUNT(*) OVER () FROM t",

            # CTEs
            "WITH cte1 AS (SELECT * FROM t WHERE a > 0), cte2 AS (SELECT * FROM t2 WHERE b < 10) SELECT * FROM cte1 JOIN cte2 ON cte1.id = cte2.id",
            "WITH RECURSIVE r AS (SELECT 1 AS n UNION ALL SELECT n + 1 FROM r WHERE n < 10) SELECT * FROM r",

            # Advanced features
            "SELECT * FROM t WHERE a > ANY (SELECT b FROM t2)",
            "SELECT * FROM t WHERE c < ALL (SELECT d FROM t2)",
            "SELECT CAST(a AS INT), CAST(b AS VARCHAR), CAST(c AS DECIMAL(10,2)) FROM t",
            "SELECT a AS x, b y FROM t AS alias",
            "SELECT a || b, 'hello' || ' world' FROM t",
            "SELECT * FROM t WHERE a IS TRUE OR b IS FALSE OR c IS NOT TRUE",
            "SELECT COUNT(DISTINCT a), COUNT(DISTINCT b) FROM t",
            "SELECT TOP 10 * FROM t",
            "SELECT TOP 10 PERCENT * FROM t",
            "SELECT ALL a FROM t",

            # Transactions
            "BEGIN TRANSACTION",
            "COMMIT",
            "ROLLBACK",

            # Complex combinations
            "SELECT t1.a, t2.b, (SELECT COUNT(*) FROM t3 WHERE t3.x = t1.x) FROM t1 LEFT JOIN t2 ON t1.id = t2.id WHERE t1.c IN (SELECT d FROM t4) AND t1.e > 0 GROUP BY t1.a, t2.b HAVING SUM(t2.f) > 100 ORDER BY t1.a, t2.b LIMIT 50 OFFSET 10",

            # Edge cases
            "SELECT 1",
            "SELECT 1 + 2 * 3 - 4 / 2",
            "SELECT * FROM t WHERE a = 0",
            "SELECT * FROM t WHERE b = ''",
            "SELECT DISTINCT a, b FROM t",
            "SELECT * FROM t, t2 WHERE t.id = t2.t_id",
            "SELECT * FROM t ORDER BY a NULLS FIRST",
            "SELECT * FROM t OFFSET 5",
            "SELECT * FROM t LIMIT 10 OFFSET 5",
            "SELECT COUNT(*) FROM t",
            "INSERT INTO t DEFAULT VALUES",
            "UPDATE t SET a = a + 1",
            "DELETE FROM t",
            "CREATE TABLE t (a INT)",
            "DROP TABLE t",
            "SELECT * FROM (SELECT * FROM t) AS sub",
        ]
