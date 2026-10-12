class Solution:
    def solve(self, resources_path: str) -> list[str]:
        """Target parser methods systematically for maximum branch coverage."""

        tests = []

        # 1. Statement-level parsing methods (parse_statement branches)
        tests.extend([
            "SELECT * FROM t",                    # SELECT statement
            "INSERT INTO t VALUES (1)",           # INSERT statement
            "UPDATE t SET a = 1",                 # UPDATE statement
            "DELETE FROM t",                      # DELETE statement
            "CREATE TABLE t (id INT)",            # CREATE TABLE
            "DROP TABLE t",                       # DROP TABLE
            "ALTER TABLE t ADD COLUMN x INT",     # ALTER TABLE
            "CREATE INDEX i ON t(a)",             # CREATE INDEX
            "DROP INDEX i",                       # DROP INDEX
            "CREATE VIEW v AS SELECT * FROM t",   # CREATE VIEW
            "DROP VIEW v",                        # DROP VIEW
            "TRUNCATE TABLE t",                   # TRUNCATE
            "BEGIN",                              # BEGIN
            "COMMIT",                             # COMMIT
            "ROLLBACK",                           # ROLLBACK
            "BEGIN TRANSACTION",                  # BEGIN TRANSACTION
        ])

        # 2. SELECT clause variations (parse_select branches)
        tests.extend([
            "SELECT a FROM t",
            "SELECT * FROM t",
            "SELECT DISTINCT a FROM t",
            "SELECT ALL a FROM t",
            "SELECT TOP 10 * FROM t",
            "SELECT TOP 10 PERCENT * FROM t",
            "SELECT a, b, c FROM t",
            "SELECT t.a FROM t",
            "SELECT t.* FROM t",
            "SELECT a AS alias FROM t",
            "SELECT a alias FROM t",
        ])

        # 3. FROM clause variations (parse_from branches)
        tests.extend([
            "SELECT * FROM t",
            "SELECT * FROM t AS alias",
            "SELECT * FROM t alias",
            "SELECT * FROM t1, t2",
            "SELECT * FROM t1, t2, t3",
            "SELECT * FROM (SELECT * FROM t) AS sub",
        ])

        # 4. JOIN variations (parse_join branches)
        tests.extend([
            "SELECT * FROM t1 JOIN t2 ON t1.id = t2.id",
            "SELECT * FROM t1 INNER JOIN t2 ON t1.id = t2.id",
            "SELECT * FROM t1 LEFT JOIN t2 ON t1.id = t2.id",
            "SELECT * FROM t1 RIGHT JOIN t2 ON t1.id = t2.id",
            "SELECT * FROM t1 FULL JOIN t2 ON t1.id = t2.id",
            "SELECT * FROM t1 LEFT OUTER JOIN t2 ON t1.id = t2.id",
            "SELECT * FROM t1 RIGHT OUTER JOIN t2 ON t1.id = t2.id",
            "SELECT * FROM t1 FULL OUTER JOIN t2 ON t1.id = t2.id",
            "SELECT * FROM t1 CROSS JOIN t2",
            "SELECT * FROM t1 NATURAL JOIN t2",
            "SELECT * FROM t1 JOIN t2 USING (id)",
            "SELECT * FROM t1 JOIN t2 ON t1.a = t2.a AND t1.b = t2.b",
        ])

        # 5. WHERE clause (parse_where branches)
        tests.extend([
            "SELECT * FROM t WHERE a = 1",
            "SELECT * FROM t WHERE a > 1",
            "SELECT * FROM t WHERE a < 1",
            "SELECT * FROM t WHERE a >= 1",
            "SELECT * FROM t WHERE a <= 1",
            "SELECT * FROM t WHERE a <> 1",
            "SELECT * FROM t WHERE a != 1",
            "SELECT * FROM t WHERE a IS NULL",
            "SELECT * FROM t WHERE a IS NOT NULL",
            "SELECT * FROM t WHERE a IN (1, 2, 3)",
            "SELECT * FROM t WHERE a NOT IN (1, 2)",
            "SELECT * FROM t WHERE a BETWEEN 1 AND 10",
            "SELECT * FROM t WHERE a NOT BETWEEN 1 AND 10",
            "SELECT * FROM t WHERE a LIKE 'x%'",
            "SELECT * FROM t WHERE a NOT LIKE 'x%'",
            "SELECT * FROM t WHERE a AND b",
            "SELECT * FROM t WHERE a OR b",
            "SELECT * FROM t WHERE NOT a",
            "SELECT * FROM t WHERE (a AND b) OR c",
            "SELECT * FROM t WHERE a > ANY (SELECT b FROM t2)",
            "SELECT * FROM t WHERE a < ALL (SELECT b FROM t2)",
            "SELECT * FROM t WHERE a = SOME (SELECT b FROM t2)",
            "SELECT * FROM t WHERE EXISTS (SELECT 1 FROM t2)",
            "SELECT * FROM t WHERE NOT EXISTS (SELECT 1 FROM t2)",
        ])

        # 6. GROUP BY clause (parse_group_by branches)
        tests.extend([
            "SELECT a FROM t GROUP BY a",
            "SELECT a, b FROM t GROUP BY a, b",
            "SELECT a, COUNT(*) FROM t GROUP BY a",
        ])

        # 7. HAVING clause (parse_having branches)
        tests.extend([
            "SELECT a FROM t GROUP BY a HAVING COUNT(*) > 1",
            "SELECT a FROM t GROUP BY a HAVING SUM(b) > 10",
            "SELECT a FROM t GROUP BY a HAVING AVG(b) > 5 AND MAX(b) < 100",
        ])

        # 8. ORDER BY clause (parse_order_by branches)
        tests.extend([
            "SELECT * FROM t ORDER BY a",
            "SELECT * FROM t ORDER BY a ASC",
            "SELECT * FROM t ORDER BY a DESC",
            "SELECT * FROM t ORDER BY a, b",
            "SELECT * FROM t ORDER BY a ASC, b DESC",
            "SELECT * FROM t ORDER BY 1",
            "SELECT * FROM t ORDER BY a NULLS FIRST",
            "SELECT * FROM t ORDER BY a NULLS LAST",
        ])

        # 9. LIMIT/OFFSET clause (parse_limit branches)
        tests.extend([
            "SELECT * FROM t LIMIT 10",
            "SELECT * FROM t OFFSET 5",
            "SELECT * FROM t LIMIT 10 OFFSET 5",
        ])

        # 10. Expression parsing (parse_expression branches)
        tests.extend([
            "SELECT 1",
            "SELECT 1 + 2",
            "SELECT 1 - 2",
            "SELECT 1 * 2",
            "SELECT 1 / 2",
            "SELECT 1 % 2",
            "SELECT -1",
            "SELECT +1",
            "SELECT (1 + 2)",
            "SELECT (1 + 2) * 3",
            "SELECT a + b FROM t",
            "SELECT a - b FROM t",
            "SELECT a * b FROM t",
            "SELECT a / b FROM t",
            "SELECT a % b FROM t",
            "SELECT a + b * c FROM t",
            "SELECT (a + b) * c FROM t",
        ])

        # 11. Literal parsing (parse_literal branches)
        tests.extend([
            "SELECT 0",
            "SELECT 123",
            "SELECT -456",
            "SELECT 1.5",
            "SELECT -2.5",
            "SELECT 1e5",
            "SELECT 1e-5",
            "SELECT 1.5e10",
            "SELECT 'string'",
            "SELECT ''",
            "SELECT 'can''t'",
            "SELECT NULL",
            "SELECT TRUE",
            "SELECT FALSE",
        ])

        # 12. Function calls (parse_function branches)
        tests.extend([
            "SELECT COUNT(*) FROM t",
            "SELECT COUNT(a) FROM t",
            "SELECT COUNT(DISTINCT a) FROM t",
            "SELECT SUM(a) FROM t",
            "SELECT AVG(a) FROM t",
            "SELECT MIN(a) FROM t",
            "SELECT MAX(a) FROM t",
            "SELECT UPPER(a) FROM t",
            "SELECT LOWER(a) FROM t",
            "SELECT LENGTH(a) FROM t",
            "SELECT SUBSTRING(a, 1, 10) FROM t",
            "SELECT CONCAT(a, b) FROM t",
            "SELECT COALESCE(a, b, 0) FROM t",
            "SELECT NULLIF(a, 0) FROM t",
            "SELECT ROUND(a, 2) FROM t",
            "SELECT ABS(a) FROM t",
            "SELECT TRIM(a) FROM t",
            "SELECT LTRIM(a) FROM t",
            "SELECT RTRIM(a) FROM t",
            "SELECT NOW()",
            "SELECT CURRENT_DATE",
            "SELECT CURRENT_TIME",
            "SELECT CURRENT_TIMESTAMP",
        ])

        # 13. CASE expressions (parse_case branches)
        tests.extend([
            "SELECT CASE WHEN a > 0 THEN 1 ELSE 0 END FROM t",
            "SELECT CASE WHEN a > 0 THEN 1 WHEN a < 0 THEN -1 ELSE 0 END FROM t",
            "SELECT CASE a WHEN 1 THEN 'one' WHEN 2 THEN 'two' ELSE 'other' END FROM t",
            "SELECT CASE WHEN a > 0 THEN 1 END FROM t",
        ])

        # 14. Subqueries (parse_subquery branches)
        tests.extend([
            "SELECT * FROM (SELECT * FROM t) AS sub",
            "SELECT * FROM t WHERE a IN (SELECT b FROM t2)",
            "SELECT * FROM t WHERE a = (SELECT MAX(b) FROM t2)",
            "SELECT a, (SELECT COUNT(*) FROM t2) FROM t",
            "SELECT * FROM t WHERE a > (SELECT AVG(b) FROM t2 WHERE t2.id = t.id)",
        ])

        # 15. Set operations (parse_set_op branches)
        tests.extend([
            "SELECT a FROM t1 UNION SELECT a FROM t2",
            "SELECT a FROM t1 UNION ALL SELECT a FROM t2",
            "SELECT a FROM t1 INTERSECT SELECT a FROM t2",
            "SELECT a FROM t1 EXCEPT SELECT a FROM t2",
        ])

        # 16. Window functions (parse_window branches)
        tests.extend([
            "SELECT ROW_NUMBER() OVER (ORDER BY a) FROM t",
            "SELECT RANK() OVER (ORDER BY a) FROM t",
            "SELECT DENSE_RANK() OVER (ORDER BY a) FROM t",
            "SELECT ROW_NUMBER() OVER (PARTITION BY b ORDER BY a) FROM t",
            "SELECT SUM(a) OVER (ORDER BY b) FROM t",
            "SELECT AVG(a) OVER (PARTITION BY b) FROM t",
            "SELECT LAG(a) OVER (ORDER BY b) FROM t",
            "SELECT LEAD(a) OVER (ORDER BY b) FROM t",
            "SELECT FIRST_VALUE(a) OVER (ORDER BY b) FROM t",
            "SELECT LAST_VALUE(a) OVER (ORDER BY b) FROM t",
        ])

        # 17. CTEs (parse_with branches)
        tests.extend([
            "WITH cte AS (SELECT * FROM t) SELECT * FROM cte",
            "WITH cte AS (SELECT a FROM t WHERE a > 0) SELECT * FROM cte WHERE a < 10",
            "WITH cte1 AS (SELECT * FROM t1), cte2 AS (SELECT * FROM t2) SELECT * FROM cte1 JOIN cte2 ON cte1.id = cte2.id",
            "WITH RECURSIVE cte AS (SELECT 1 AS n UNION ALL SELECT n + 1 FROM cte WHERE n < 10) SELECT * FROM cte",
        ])

        # 18. INSERT variations (parse_insert branches)
        tests.extend([
            "INSERT INTO t (a, b) VALUES (1, 2)",
            "INSERT INTO t VALUES (1, 2)",
            "INSERT INTO t (a) VALUES (1), (2), (3)",
            "INSERT INTO t SELECT * FROM t2",
            "INSERT INTO t (a, b) SELECT x, y FROM t2",
            "INSERT INTO t DEFAULT VALUES",
        ])

        # 19. UPDATE variations (parse_update branches)
        tests.extend([
            "UPDATE t SET a = 1",
            "UPDATE t SET a = 1 WHERE b = 2",
            "UPDATE t SET a = 1, b = 2",
            "UPDATE t SET a = a + 1",
            "UPDATE t SET a = (SELECT MAX(b) FROM t2)",
        ])

        # 20. DELETE variations (parse_delete branches)
        tests.extend([
            "DELETE FROM t",
            "DELETE FROM t WHERE a = 1",
            "DELETE FROM t WHERE a IN (SELECT b FROM t2)",
        ])

        # 21. CREATE TABLE variations (parse_create_table branches)
        tests.extend([
            "CREATE TABLE t (id INT)",
            "CREATE TABLE t (id INT, name VARCHAR(100))",
            "CREATE TABLE t (id INT PRIMARY KEY)",
            "CREATE TABLE t (id INT NOT NULL)",
            "CREATE TABLE t (id INT DEFAULT 0)",
            "CREATE TABLE t (id INT, name VARCHAR(100), age INT)",
            "CREATE TABLE IF NOT EXISTS t (id INT)",
        ])

        # 22. CAST expressions (parse_cast branches)
        tests.extend([
            "SELECT CAST(a AS INT) FROM t",
            "SELECT CAST(a AS VARCHAR) FROM t",
            "SELECT CAST(a AS DECIMAL(10, 2)) FROM t",
            "SELECT CAST('123' AS INT)",
        ])

        # 23. Special operators and keywords
        tests.extend([
            "SELECT * FROM t WHERE a IS TRUE",
            "SELECT * FROM t WHERE a IS FALSE",
            "SELECT * FROM t WHERE a IS NOT TRUE",
            "SELECT * FROM t WHERE a IS NOT FALSE",
            "SELECT * FROM t WHERE a IS UNKNOWN",
            "SELECT a || b FROM t",
            "SELECT 'hello' || ' ' || 'world'",
        ])

        # 24. Additional DDL
        tests.extend([
            "DROP TABLE IF EXISTS t",
            "ALTER TABLE t DROP COLUMN c",
            "CREATE UNIQUE INDEX idx ON t(a)",
            "DROP INDEX IF EXISTS idx",
            "DROP VIEW IF EXISTS v",
        ])

        # 25. Complex combined queries
        tests.extend([
            "SELECT t1.*, t2.b FROM t1 LEFT JOIN t2 ON t1.id = t2.id WHERE t1.a > 0 ORDER BY t1.a LIMIT 10",
            "SELECT a, COUNT(*) FROM t WHERE b > 0 GROUP BY a HAVING COUNT(*) > 1 ORDER BY COUNT(*) DESC",
            "SELECT * FROM (SELECT * FROM t WHERE a > 0) AS sub WHERE sub.b < 10",
        ])

        # 26. Edge cases that might trigger different parser paths
        tests.extend([
            "SELECT DISTINCT * FROM t",
            "SELECT ALL * FROM t",
            "SELECT * FROM t WHERE 1 = 1",
            "SELECT * FROM t WHERE TRUE",
            "SELECT * FROM t WHERE NOT FALSE",
            "SELECT 1 FROM t",
            "SELECT a, b, c, d, e FROM t",
        ])

        return tests
