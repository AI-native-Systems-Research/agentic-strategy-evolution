class Solution:
    def solve(self, resources_path: str) -> list[str]:
        """Generate SQL test cases to maximize parser coverage with optimal efficiency."""

        return [
            # Core SELECT forms
            "SELECT * FROM t",
            "SELECT a, b FROM t",
            "SELECT DISTINCT a FROM t",
            "SELECT ALL a FROM t",
            "SELECT t.* FROM t",
            "SELECT TOP 10 * FROM t",

            # WHERE - all operator types
            "SELECT * FROM t WHERE a = 1",
            "SELECT * FROM t WHERE a <> 1",
            "SELECT * FROM t WHERE a < 1",
            "SELECT * FROM t WHERE a <= 1",
            "SELECT * FROM t WHERE a > 1",
            "SELECT * FROM t WHERE a >= 1",
            "SELECT * FROM t WHERE a != 1",
            "SELECT * FROM t WHERE a IS NULL",
            "SELECT * FROM t WHERE a IS NOT NULL",
            "SELECT * FROM t WHERE a LIKE 'x%'",
            "SELECT * FROM t WHERE a NOT LIKE 'x%'",
            "SELECT * FROM t WHERE a IN (1, 2, 3)",
            "SELECT * FROM t WHERE a NOT IN (1, 2)",
            "SELECT * FROM t WHERE a BETWEEN 1 AND 10",
            "SELECT * FROM t WHERE a NOT BETWEEN 1 AND 10",
            "SELECT * FROM t WHERE a AND b",
            "SELECT * FROM t WHERE a OR b",
            "SELECT * FROM t WHERE NOT a",
            "SELECT * FROM t WHERE (a OR b) AND c",

            # Expressions and arithmetic
            "SELECT 1",
            "SELECT 1 + 2",
            "SELECT 1 - 2",
            "SELECT 1 * 2",
            "SELECT 1 / 2",
            "SELECT 1 % 2",
            "SELECT -1",
            "SELECT (1 + 2) * 3",
            "SELECT a + b * c FROM t",

            # All literal types
            "SELECT 0",
            "SELECT 123",
            "SELECT 1.5",
            "SELECT -2.5",
            "SELECT 1e5",
            "SELECT 1.5e-3",
            "SELECT 'string'",
            "SELECT ''",
            "SELECT 'can''t'",
            "SELECT NULL",
            "SELECT TRUE",
            "SELECT FALSE",

            # All aggregates
            "SELECT COUNT(*) FROM t",
            "SELECT COUNT(a) FROM t",
            "SELECT COUNT(DISTINCT a) FROM t",
            "SELECT SUM(a) FROM t",
            "SELECT AVG(a) FROM t",
            "SELECT MIN(a) FROM t",
            "SELECT MAX(a) FROM t",
            "SELECT COUNT(*), SUM(a), AVG(a), MIN(a), MAX(a) FROM t",

            # GROUP BY and HAVING
            "SELECT a FROM t GROUP BY a",
            "SELECT a, COUNT(*) FROM t GROUP BY a",
            "SELECT a, b FROM t GROUP BY a, b",
            "SELECT a FROM t GROUP BY a HAVING COUNT(*) > 1",
            "SELECT a FROM t GROUP BY a HAVING SUM(b) > 10",
            "SELECT a FROM t GROUP BY a HAVING AVG(b) > 10 AND MAX(b) < 100",

            # ORDER BY
            "SELECT * FROM t ORDER BY a",
            "SELECT * FROM t ORDER BY a ASC",
            "SELECT * FROM t ORDER BY a DESC",
            "SELECT * FROM t ORDER BY a, b",
            "SELECT * FROM t ORDER BY a ASC, b DESC",
            "SELECT * FROM t ORDER BY 1",
            "SELECT * FROM t ORDER BY a + b",

            # LIMIT/OFFSET
            "SELECT * FROM t LIMIT 10",
            "SELECT * FROM t OFFSET 5",
            "SELECT * FROM t LIMIT 10 OFFSET 5",

            # All JOIN types
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
            "SELECT * FROM t1, t2 WHERE t1.id = t2.id",
            "SELECT * FROM t1 JOIN t2 ON t1.a = t2.a AND t1.b = t2.b",
            "SELECT * FROM t1 JOIN t2 ON t1.id = t2.id JOIN t3 ON t2.id = t3.id",

            # Subqueries
            "SELECT * FROM (SELECT * FROM t) AS sub",
            "SELECT * FROM t WHERE a IN (SELECT b FROM t2)",
            "SELECT * FROM t WHERE a = (SELECT MAX(b) FROM t2)",
            "SELECT a, (SELECT COUNT(*) FROM t2) FROM t",
            "SELECT * FROM t WHERE EXISTS (SELECT 1 FROM t2)",
            "SELECT * FROM t WHERE NOT EXISTS (SELECT 1 FROM t2)",
            "SELECT * FROM t WHERE a IN (SELECT b FROM t2 WHERE c IN (SELECT d FROM t3))",
            "SELECT * FROM t1 WHERE a > (SELECT AVG(b) FROM t2 WHERE t2.id = t1.id)",

            # Set operations
            "SELECT a FROM t1 UNION SELECT a FROM t2",
            "SELECT a FROM t1 UNION ALL SELECT a FROM t2",
            "SELECT a FROM t1 INTERSECT SELECT a FROM t2",
            "SELECT a FROM t1 EXCEPT SELECT a FROM t2",
            "SELECT a FROM t1 UNION SELECT a FROM t2 UNION SELECT a FROM t3",

            # INSERT
            "INSERT INTO t (a, b) VALUES (1, 2)",
            "INSERT INTO t VALUES (1, 2)",
            "INSERT INTO t (a) VALUES (1), (2), (3)",
            "INSERT INTO t SELECT * FROM t2",
            "INSERT INTO t DEFAULT VALUES",

            # UPDATE
            "UPDATE t SET a = 1",
            "UPDATE t SET a = 1 WHERE b = 2",
            "UPDATE t SET a = 1, b = 2",
            "UPDATE t SET a = a + 1",
            "UPDATE t SET a = (SELECT MAX(b) FROM t2)",

            # DELETE
            "DELETE FROM t",
            "DELETE FROM t WHERE a = 1",

            # DDL
            "CREATE TABLE t (id INT)",
            "CREATE TABLE t (id INT, name VARCHAR(100))",
            "CREATE TABLE t (id INT PRIMARY KEY)",
            "CREATE TABLE t (id INT NOT NULL)",
            "CREATE TABLE t (id INT DEFAULT 0)",
            "CREATE TABLE IF NOT EXISTS t (id INT)",
            "DROP TABLE t",
            "DROP TABLE IF EXISTS t",
            "ALTER TABLE t ADD COLUMN c INT",
            "ALTER TABLE t DROP COLUMN c",
            "TRUNCATE TABLE t",
            "CREATE INDEX idx ON t(a)",
            "CREATE UNIQUE INDEX idx ON t(a)",
            "DROP INDEX idx",
            "CREATE VIEW v AS SELECT * FROM t",
            "DROP VIEW v",

            # CASE
            "SELECT CASE WHEN a > 0 THEN 1 ELSE 0 END FROM t",
            "SELECT CASE WHEN a > 0 THEN 1 WHEN a < 0 THEN -1 ELSE 0 END FROM t",
            "SELECT CASE a WHEN 1 THEN 'one' WHEN 2 THEN 'two' ELSE 'other' END FROM t",
            "SELECT CASE WHEN a > 0 THEN CASE WHEN b > 0 THEN 1 ELSE 2 END ELSE 3 END FROM t",

            # Functions
            "SELECT UPPER(a) FROM t",
            "SELECT LOWER(a) FROM t",
            "SELECT LENGTH(a) FROM t",
            "SELECT TRIM(a) FROM t",
            "SELECT LTRIM(a) FROM t",
            "SELECT RTRIM(a) FROM t",
            "SELECT SUBSTRING(a, 1, 10) FROM t",
            "SELECT CONCAT(a, b) FROM t",
            "SELECT COALESCE(a, b, 0) FROM t",
            "SELECT NULLIF(a, 0) FROM t",
            "SELECT ABS(a) FROM t",
            "SELECT ROUND(a, 2) FROM t",
            "SELECT FLOOR(a) FROM t",
            "SELECT CEIL(a) FROM t",
            "SELECT SQRT(a) FROM t",
            "SELECT POWER(a, 2) FROM t",
            "SELECT NOW()",
            "SELECT CURRENT_DATE",
            "SELECT CURRENT_TIME",
            "SELECT CURRENT_TIMESTAMP",
            "SELECT UPPER(TRIM(a)) FROM t",

            # Window functions
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

            # CTEs
            "WITH cte AS (SELECT * FROM t) SELECT * FROM cte",
            "WITH cte AS (SELECT a FROM t WHERE a > 0) SELECT * FROM cte WHERE a < 10",
            "WITH cte1 AS (SELECT * FROM t1), cte2 AS (SELECT * FROM t2) SELECT * FROM cte1 JOIN cte2 ON cte1.id = cte2.id",
            "WITH RECURSIVE cte AS (SELECT 1 AS n UNION ALL SELECT n + 1 FROM cte WHERE n < 10) SELECT * FROM cte",

            # Transactions
            "BEGIN",
            "COMMIT",
            "ROLLBACK",
            "BEGIN TRANSACTION",

            # ANY/ALL
            "SELECT * FROM t WHERE a > ANY (SELECT b FROM t2)",
            "SELECT * FROM t WHERE a > ALL (SELECT b FROM t2)",
            "SELECT * FROM t WHERE a = SOME (SELECT b FROM t2)",

            # CAST
            "SELECT CAST(a AS INT) FROM t",
            "SELECT CAST(a AS VARCHAR) FROM t",
            "SELECT CAST(a AS DECIMAL(10, 2)) FROM t",

            # Aliases
            "SELECT a AS alias FROM t",
            "SELECT a alias FROM t",
            "SELECT * FROM t AS alias",

            # String concatenation
            "SELECT a || b FROM t",
            "SELECT 'hello' || ' ' || 'world'",

            # IS TRUE/FALSE
            "SELECT * FROM t WHERE a IS TRUE",
            "SELECT * FROM t WHERE a IS FALSE",
            "SELECT * FROM t WHERE a IS NOT TRUE",

            # Date functions
            "SELECT EXTRACT(YEAR FROM date_col) FROM t",
            "SELECT EXTRACT(MONTH FROM date_col) FROM t",
            "SELECT EXTRACT(DAY FROM date_col) FROM t",
            "SELECT DATE_ADD(date_col, INTERVAL 1 DAY) FROM t",
            "SELECT DATE_SUB(date_col, INTERVAL 1 MONTH) FROM t",
            "SELECT DATEDIFF(date1, date2) FROM t",

            # Complex queries
            "SELECT * FROM t WHERE a IN (SELECT b FROM t2) AND c > 0",
            "SELECT t1.*, t2.* FROM t1 LEFT JOIN t2 ON t1.id = t2.id WHERE t1.a > 0 ORDER BY t1.a",
            "SELECT a, COUNT(*) FROM t WHERE b > 0 GROUP BY a HAVING COUNT(*) > 1 ORDER BY COUNT(*) DESC",
            "SELECT DISTINCT a FROM t WHERE b IN (SELECT c FROM t2) ORDER BY a LIMIT 10",
            "INSERT INTO t (a, b) SELECT x, y FROM t2 WHERE z > 0",
            "UPDATE t SET a = (SELECT MAX(x) FROM t2) WHERE b = 1",
            "DELETE FROM t WHERE a IN (SELECT b FROM t2 WHERE c = 1)",

            # Edge cases
            "SELECT * FROM t WHERE (a OR b) AND (c OR d)",
            "SELECT * FROM t WHERE NOT (a AND b)",
            "SELECT * FROM (SELECT * FROM t ORDER BY a LIMIT 10) AS sub",
            "SELECT * FROM t t1 JOIN t t2 ON t1.parent_id = t2.id",
            "SELECT a + b, a - b, a * b, a / b, a % b FROM t",
            "SELECT DISTINCT a, b FROM t",
            "SELECT 1 + 2",
            "SELECT * FROM t ORDER BY NULLS FIRST",
            "SELECT TOP 10 PERCENT * FROM t",
        ]
