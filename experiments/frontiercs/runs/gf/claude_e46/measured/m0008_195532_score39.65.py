import os

class Solution:
    def solve(self, resources_path: str) -> list[str]:
        return [
            # 1. Mega SELECT covering most SELECT features: DISTINCT, aliases, WHERE with all ops,
            # GROUP BY, HAVING, ORDER BY, LIMIT OFFSET, aggregates, CASE, functions, window
            "SELECT DISTINCT a AS x, t.b, t.*, COUNT(*), COUNT(DISTINCT c), SUM(d), AVG(e), MIN(f), MAX(g), "
            "CASE WHEN a = 1 THEN 'one' WHEN a = 2 THEN 'two' ELSE 'other' END, "
            "CASE a WHEN 1 THEN 'x' WHEN 2 THEN 'y' END, "
            "UPPER(a), LOWER(b), LENGTH(c), TRIM(d), TRIM(LEADING ' ' FROM e), TRIM(TRAILING ' ' FROM f), TRIM(BOTH ' ' FROM g), "
            "SUBSTRING(a FROM 1 FOR 3), SUBSTRING(b, 1, 3), REPLACE(c, 'x', 'y'), POSITION('x' IN d), "
            "COALESCE(a, b, c), NULLIF(a, b), GREATEST(a, b), LEAST(a, b), "
            "CAST(a AS INT), CAST(b AS VARCHAR(100)), a::INT, "
            "CONCAT(a, b), LEFT(a, 3), RIGHT(a, 3), "
            "ABS(a), ROUND(a, 2), "
            "NOW(), CURRENT_TIMESTAMP, CURRENT_DATE, CURRENT_TIME, "
            "EXTRACT(YEAR FROM h), EXTRACT(MONTH FROM h), EXTRACT(DAY FROM h), EXTRACT(HOUR FROM h), "
            "ROW_NUMBER() OVER (ORDER BY a), "
            "RANK() OVER (PARTITION BY b ORDER BY a), "
            "DENSE_RANK() OVER (ORDER BY a DESC), "
            "LAG(a, 1) OVER (ORDER BY a), LEAD(a, 1) OVER (ORDER BY a), "
            "LAG(a, 1, 0) OVER (ORDER BY a), "
            "FIRST_VALUE(a) OVER (ORDER BY a), LAST_VALUE(a) OVER (ORDER BY a), "
            "NTH_VALUE(a, 2) OVER (ORDER BY a), "
            "NTILE(4) OVER (ORDER BY a), "
            "PERCENT_RANK() OVER (ORDER BY a), CUME_DIST() OVER (ORDER BY a), "
            "SUM(b) OVER (ORDER BY a ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW), "
            "SUM(b) OVER (ORDER BY a ROWS BETWEEN 1 PRECEDING AND 1 FOLLOWING), "
            "SUM(b) OVER (ORDER BY a RANGE BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING), "
            "SUM(b) OVER (ORDER BY a ROWS BETWEEN CURRENT ROW AND UNBOUNDED FOLLOWING), "
            "COUNT(*) OVER (), "
            "(SELECT MAX(z) FROM t2), "
            "'hello', 3.14, -42, TRUE, FALSE, NULL, "
            "a + b, a - b, a * b, a / b, a % b, -a, a || b "
            "FROM t "
            "WHERE a = 1 AND b != 2 AND c <> 3 AND d > 4 AND e < 5 AND f >= 6 AND g <= 7 "
            "AND h LIKE '%x%' AND i NOT LIKE 'x%' "
            "AND j IN (1, 2, 3) AND k NOT IN (4, 5) "
            "AND l BETWEEN 1 AND 10 AND m NOT BETWEEN 20 AND 30 "
            "AND n IS NULL AND o IS NOT NULL "
            "AND NOT p = 0 AND (q = 1 OR r = 2) "
            "GROUP BY a, b "
            "HAVING COUNT(*) > 1 "
            "ORDER BY a ASC, b DESC NULLS FIRST "
            "LIMIT 10 OFFSET 5",

            # 2. Window with named window
            "SELECT SUM(b) OVER w FROM t WINDOW w AS (PARTITION BY c ORDER BY d)",

            # 3. All JOIN types
            "SELECT a FROM t1 JOIN t2 ON t1.id = t2.id",
            "SELECT a FROM t1 INNER JOIN t2 ON t1.id = t2.id",
            "SELECT a FROM t1 LEFT JOIN t2 ON t1.id = t2.id",
            "SELECT a FROM t1 LEFT OUTER JOIN t2 ON t1.id = t2.id",
            "SELECT a FROM t1 RIGHT JOIN t2 ON t1.id = t2.id",
            "SELECT a FROM t1 RIGHT OUTER JOIN t2 ON t1.id = t2.id",
            "SELECT a FROM t1 FULL JOIN t2 ON t1.id = t2.id",
            "SELECT a FROM t1 FULL OUTER JOIN t2 ON t1.id = t2.id",
            "SELECT a FROM t1 CROSS JOIN t2",
            "SELECT a FROM t1 NATURAL JOIN t2",
            "SELECT a FROM t1 JOIN t2 USING (id)",
            "SELECT a FROM t1 JOIN t2 USING (id, name)",

            # 4. Subqueries
            "SELECT a FROM (SELECT b FROM t) AS sub",
            "SELECT a FROM t WHERE a IN (SELECT b FROM t2)",
            "SELECT a FROM t WHERE EXISTS (SELECT 1 FROM t2 WHERE t2.id = t.id)",
            "SELECT a FROM t WHERE NOT EXISTS (SELECT 1 FROM t2)",
            "SELECT a FROM t WHERE a > ANY (SELECT b FROM t2)",
            "SELECT a FROM t WHERE a > ALL (SELECT b FROM t2)",

            # 5. Set operations
            "SELECT a FROM t1 UNION SELECT b FROM t2",
            "SELECT a FROM t1 UNION ALL SELECT b FROM t2",
            "SELECT a FROM t1 INTERSECT SELECT b FROM t2",
            "SELECT a FROM t1 EXCEPT SELECT b FROM t2",

            # 6. INSERT variants
            "INSERT INTO t (a, b) VALUES (1, 2)",
            "INSERT INTO t VALUES (1, 2, 3)",
            "INSERT INTO t (a) VALUES (1), (2), (3)",
            "INSERT INTO t SELECT a FROM t2",
            "INSERT INTO t DEFAULT VALUES",

            # 7. UPDATE / DELETE
            "UPDATE t SET a = 1, b = 2 WHERE c = 3",
            "DELETE FROM t WHERE a = 1",
            "DELETE FROM t",

            # 8. CREATE TABLE with all column types and constraints
            "CREATE TABLE t (a INT PRIMARY KEY, b VARCHAR(255) NOT NULL, c FLOAT DEFAULT 0.0, d BOOLEAN, e DATE, f TIMESTAMP, g TEXT UNIQUE, h DECIMAL(10, 2), i NUMERIC, j BIGINT, k SMALLINT, l REAL, m DOUBLE PRECISION, n SERIAL, o CHAR(10), p INTEGER)",
            "CREATE TABLE IF NOT EXISTS t (a INT)",
            "CREATE TABLE t (a INT, b INT, PRIMARY KEY (a, b))",
            "CREATE TABLE t (a INT REFERENCES other(id))",
            "CREATE TABLE t (a INT CHECK (a > 0))",
            "CREATE TABLE t (a INT, UNIQUE (a))",
            "CREATE TABLE t (a INT, b INT, FOREIGN KEY (a) REFERENCES other(id))",
            "CREATE TABLE t (a INTEGER NOT NULL DEFAULT 0 UNIQUE CHECK (a >= 0))",
            "CREATE TEMPORARY TABLE t (a INT)",
            "CREATE TEMP TABLE t (a INT)",

            # 9. DROP TABLE
            "DROP TABLE t",
            "DROP TABLE IF EXISTS t",
            "DROP TABLE t CASCADE",
            "DROP TABLE t RESTRICT",

            # 10. CREATE/DROP INDEX
            "CREATE INDEX idx ON t (a)",
            "CREATE UNIQUE INDEX idx ON t (a, b)",
            "CREATE INDEX IF NOT EXISTS idx ON t (a)",
            "DROP INDEX idx",
            "DROP INDEX IF EXISTS idx",

            # 11. ALTER TABLE (all variants)
            "ALTER TABLE t ADD COLUMN a INT",
            "ALTER TABLE t ADD a INT",
            "ALTER TABLE t DROP COLUMN a",
            "ALTER TABLE t RENAME TO t2",
            "ALTER TABLE t RENAME COLUMN a TO b",
            "ALTER TABLE t ALTER COLUMN a SET DEFAULT 0",
            "ALTER TABLE t ALTER COLUMN a DROP DEFAULT",
            "ALTER TABLE t ALTER COLUMN a SET NOT NULL",
            "ALTER TABLE t ALTER COLUMN a DROP NOT NULL",
            "ALTER TABLE t ALTER COLUMN a TYPE VARCHAR(100)",
            "ALTER TABLE t ADD CONSTRAINT pk PRIMARY KEY (a)",
            "ALTER TABLE t ADD CONSTRAINT uq UNIQUE (a)",
            "ALTER TABLE t ADD CONSTRAINT fk FOREIGN KEY (a) REFERENCES other(id)",
            "ALTER TABLE t ADD CONSTRAINT ck CHECK (a > 0)",
            "ALTER TABLE t DROP CONSTRAINT pk",
            "ALTER TABLE t DROP CONSTRAINT IF EXISTS pk",

            # 12. CTEs
            "WITH cte AS (SELECT a FROM t) SELECT * FROM cte",
            "WITH cte1 AS (SELECT a FROM t1), cte2 AS (SELECT b FROM t2) SELECT * FROM cte1 JOIN cte2 ON cte1.a = cte2.b",
            "WITH RECURSIVE cte AS (SELECT 1 AS n UNION ALL SELECT n + 1 FROM cte WHERE n < 10) SELECT * FROM cte",

            # 13. CREATE/DROP VIEW
            "CREATE VIEW v AS SELECT a FROM t",
            "CREATE OR REPLACE VIEW v AS SELECT a FROM t",
            "DROP VIEW v",
            "DROP VIEW IF EXISTS v",

            # 14. Transactions
            "BEGIN",
            "BEGIN TRANSACTION",
            "START TRANSACTION",
            "COMMIT",
            "ROLLBACK",
            "SAVEPOINT sp1",
            "RELEASE SAVEPOINT sp1",
            "ROLLBACK TO SAVEPOINT sp1",
            "ROLLBACK TO sp1",

            # 15. EXPLAIN
            "EXPLAIN SELECT a FROM t",
            "EXPLAIN ANALYZE SELECT a FROM t",

            # 16. TRUNCATE
            "TRUNCATE TABLE t",
            "TRUNCATE t",

            # 17. GRANT / REVOKE
            "GRANT SELECT ON t TO user1",
            "GRANT ALL ON t TO user1",
            "GRANT INSERT, UPDATE ON t TO user1",
            "REVOKE SELECT ON t FROM user1",

            # 18. UPSERT / MERGE
            "MERGE INTO t1 USING t2 ON t1.id = t2.id WHEN MATCHED THEN UPDATE SET a = t2.a WHEN NOT MATCHED THEN INSERT (id, a) VALUES (t2.id, t2.a)",
            "INSERT INTO t (a, b) VALUES (1, 2) ON CONFLICT (a) DO UPDATE SET b = 2",
            "INSERT INTO t (a, b) VALUES (1, 2) ON CONFLICT (a) DO NOTHING",

            # 19. Typed literals
            "SELECT DATE '2023-01-01'",
            "SELECT TIME '12:00:00'",
            "SELECT TIMESTAMP '2023-01-01 00:00:00'",
            "SELECT INTERVAL '1 day'",

            # 20. Misc
            "SELECT a FROM t FOR UPDATE",
            "SELECT a FROM t FOR SHARE",
            "SET search_path TO public",

            # 21. Additional features
            "SELECT a FROM t ORDER BY a DESC NULLS LAST",
            "SELECT ALL a FROM t",
        ]
