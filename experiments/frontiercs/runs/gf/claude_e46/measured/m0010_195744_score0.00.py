import os
import sys

class Solution:
    def solve(self, resources_path: str) -> list[str]:
        # Add sql_engine to path and import parse_sql
        engine_path = resources_path
        if engine_path not in sys.path:
            sys.path.insert(0, engine_path)

        parse_fn = None
        try:
            # Clean cached modules
            for mod_name in list(sys.modules.keys()):
                if 'sql_engine' in mod_name:
                    del sys.modules[mod_name]

            from sql_engine.parser import parse_sql
            parse_fn = parse_sql
        except ImportError:
            try:
                from sql_engine import parse_sql
                parse_fn = parse_sql
            except ImportError:
                pass

        if parse_fn is None:
            try:
                import importlib
                spec = importlib.util.spec_from_file_location(
                    "sql_engine.parser",
                    os.path.join(resources_path, "sql_engine", "parser.py")
                )
                mod = importlib.util.module_from_spec(spec)
                sys.modules["sql_engine.parser"] = mod
                spec.loader.exec_module(mod)
                if hasattr(mod, 'parse_sql'):
                    parse_fn = mod.parse_sql
                elif hasattr(mod, 'Parser'):
                    p = mod.Parser()
                    parse_fn = getattr(p, 'parse', getattr(p, 'parse_sql', None))
            except:
                pass

        # Build candidate statements
        candidates = self._all_candidates()

        if parse_fn is None:
            return candidates

        # Filter to only valid statements
        valid = []
        for stmt in candidates:
            try:
                parse_fn(stmt)
                valid.append(stmt)
            except:
                pass

        return valid if valid else candidates

    def _all_candidates(self):
        return [
            # Basic SELECT
            "SELECT 1",
            "SELECT a FROM t",
            "SELECT a, b, c FROM t",
            "SELECT * FROM t",
            "SELECT DISTINCT a FROM t",
            "SELECT ALL a FROM t",

            # Aliases
            "SELECT a AS x FROM t",
            "SELECT a AS x, b AS y FROM t AS z",
            "SELECT t.a FROM t",
            "SELECT t.* FROM t",

            # WHERE: comparison operators
            "SELECT a FROM t WHERE a = 1",
            "SELECT a FROM t WHERE a != 1",
            "SELECT a FROM t WHERE a <> 1",
            "SELECT a FROM t WHERE a > 1",
            "SELECT a FROM t WHERE a < 1",
            "SELECT a FROM t WHERE a >= 1",
            "SELECT a FROM t WHERE a <= 1",

            # WHERE: LIKE, IN, BETWEEN, IS NULL
            "SELECT a FROM t WHERE a LIKE '%test%'",
            "SELECT a FROM t WHERE a NOT LIKE 'test%'",
            "SELECT a FROM t WHERE a IN (1, 2, 3)",
            "SELECT a FROM t WHERE a NOT IN (1, 2)",
            "SELECT a FROM t WHERE a BETWEEN 1 AND 10",
            "SELECT a FROM t WHERE a NOT BETWEEN 1 AND 10",
            "SELECT a FROM t WHERE a IS NULL",
            "SELECT a FROM t WHERE a IS NOT NULL",

            # Logical
            "SELECT a FROM t WHERE a = 1 AND b = 2",
            "SELECT a FROM t WHERE a = 1 OR b = 2",
            "SELECT a FROM t WHERE NOT a = 1",
            "SELECT a FROM t WHERE (a = 1 OR b = 2) AND c = 3",

            # Arithmetic
            "SELECT a + b FROM t",
            "SELECT a - b FROM t",
            "SELECT a * b FROM t",
            "SELECT a / b FROM t",
            "SELECT a % b FROM t",
            "SELECT -a FROM t",
            "SELECT +a FROM t",

            # Literals
            "SELECT 'hello'",
            "SELECT 3.14",
            "SELECT -3.14",
            "SELECT 0",
            "SELECT TRUE, FALSE",
            "SELECT NULL",

            # String concat
            "SELECT a || b FROM t",

            # Aggregate functions
            "SELECT COUNT(*) FROM t",
            "SELECT COUNT(a) FROM t",
            "SELECT COUNT(DISTINCT a) FROM t",
            "SELECT SUM(a) FROM t",
            "SELECT AVG(a) FROM t",
            "SELECT MIN(a) FROM t",
            "SELECT MAX(a) FROM t",

            # GROUP BY / HAVING
            "SELECT a, COUNT(*) FROM t GROUP BY a",
            "SELECT a, COUNT(*) FROM t GROUP BY a HAVING COUNT(*) > 1",
            "SELECT a, b, SUM(c) FROM t GROUP BY a, b",

            # ORDER BY
            "SELECT a FROM t ORDER BY a",
            "SELECT a FROM t ORDER BY a ASC",
            "SELECT a FROM t ORDER BY a DESC",
            "SELECT a FROM t ORDER BY a, b DESC",
            "SELECT a FROM t ORDER BY 1",

            # LIMIT / OFFSET
            "SELECT a FROM t LIMIT 10",
            "SELECT a FROM t LIMIT 10 OFFSET 5",

            # JOINs
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
            "SELECT a FROM t1 JOIN t2 ON t1.id = t2.id JOIN t3 ON t2.id = t3.id",

            # Subqueries
            "SELECT a FROM (SELECT b FROM t) AS sub",
            "SELECT a FROM t WHERE a IN (SELECT b FROM t2)",
            "SELECT a FROM t WHERE EXISTS (SELECT 1 FROM t2 WHERE t2.id = t.id)",
            "SELECT a FROM t WHERE NOT EXISTS (SELECT 1 FROM t2)",
            "SELECT (SELECT MAX(a) FROM t2) AS m FROM t",
            "SELECT a FROM t WHERE a > ANY (SELECT b FROM t2)",
            "SELECT a FROM t WHERE a > ALL (SELECT b FROM t2)",

            # Set operations
            "SELECT a FROM t1 UNION SELECT b FROM t2",
            "SELECT a FROM t1 UNION ALL SELECT b FROM t2",
            "SELECT a FROM t1 INTERSECT SELECT b FROM t2",
            "SELECT a FROM t1 EXCEPT SELECT b FROM t2",

            # INSERT
            "INSERT INTO t (a, b) VALUES (1, 2)",
            "INSERT INTO t VALUES (1, 2, 3)",
            "INSERT INTO t (a) VALUES (1), (2), (3)",
            "INSERT INTO t SELECT a FROM t2",
            "INSERT INTO t DEFAULT VALUES",

            # UPDATE
            "UPDATE t SET a = 1",
            "UPDATE t SET a = 1, b = 2",
            "UPDATE t SET a = 1 WHERE b = 2",

            # DELETE
            "DELETE FROM t",
            "DELETE FROM t WHERE a = 1",

            # CREATE TABLE
            "CREATE TABLE t (a INT)",
            "CREATE TABLE t (a INT, b VARCHAR(255), c FLOAT)",
            "CREATE TABLE t (a INT PRIMARY KEY, b TEXT NOT NULL)",
            "CREATE TABLE t (a INT, b INT, PRIMARY KEY (a))",
            "CREATE TABLE t (a INT UNIQUE, b INT DEFAULT 0)",
            "CREATE TABLE t (a INT REFERENCES other(id))",
            "CREATE TABLE t (a INT CHECK (a > 0))",
            "CREATE TABLE IF NOT EXISTS t (a INT)",
            "CREATE TABLE t (a INTEGER, b REAL, c BOOLEAN, d DATE, e TIMESTAMP)",
            "CREATE TABLE t (a DECIMAL(10, 2))",
            "CREATE TABLE t (a VARCHAR(100))",
            "CREATE TABLE t (a CHAR(10))",

            # DROP TABLE
            "DROP TABLE t",
            "DROP TABLE IF EXISTS t",

            # CREATE / DROP INDEX
            "CREATE INDEX idx ON t (a)",
            "CREATE UNIQUE INDEX idx ON t (a, b)",
            "CREATE INDEX IF NOT EXISTS idx ON t (a)",
            "DROP INDEX idx",
            "DROP INDEX IF EXISTS idx",

            # ALTER TABLE
            "ALTER TABLE t ADD COLUMN a INT",
            "ALTER TABLE t DROP COLUMN a",
            "ALTER TABLE t RENAME TO t2",
            "ALTER TABLE t RENAME COLUMN a TO b",
            "ALTER TABLE t ALTER COLUMN a SET DEFAULT 0",
            "ALTER TABLE t ALTER COLUMN a DROP DEFAULT",
            "ALTER TABLE t ALTER COLUMN a SET NOT NULL",
            "ALTER TABLE t ALTER COLUMN a DROP NOT NULL",
            "ALTER TABLE t ADD CONSTRAINT pk PRIMARY KEY (a)",
            "ALTER TABLE t ADD CONSTRAINT uq UNIQUE (a)",
            "ALTER TABLE t ADD CONSTRAINT fk FOREIGN KEY (a) REFERENCES other(id)",
            "ALTER TABLE t DROP CONSTRAINT pk",

            # CASE
            "SELECT CASE WHEN a = 1 THEN 'one' WHEN a = 2 THEN 'two' ELSE 'other' END FROM t",
            "SELECT CASE a WHEN 1 THEN 'one' WHEN 2 THEN 'two' END FROM t",

            # Functions
            "SELECT UPPER(a) FROM t",
            "SELECT LOWER(a) FROM t",
            "SELECT LENGTH(a) FROM t",
            "SELECT TRIM(a) FROM t",
            "SELECT SUBSTRING(a FROM 1 FOR 3) FROM t",
            "SELECT SUBSTR(a, 1, 3) FROM t",
            "SELECT COALESCE(a, b, c) FROM t",
            "SELECT NULLIF(a, b) FROM t",
            "SELECT CAST(a AS INT) FROM t",
            "SELECT CAST(a AS VARCHAR(100)) FROM t",
            "SELECT ABS(a) FROM t",
            "SELECT ROUND(a, 2) FROM t",
            "SELECT CONCAT(a, b) FROM t",
            "SELECT NOW()",
            "SELECT CURRENT_TIMESTAMP",
            "SELECT CURRENT_DATE",

            # Window functions
            "SELECT a, ROW_NUMBER() OVER (ORDER BY a) FROM t",
            "SELECT a, RANK() OVER (PARTITION BY b ORDER BY a) FROM t",
            "SELECT a, DENSE_RANK() OVER (ORDER BY a DESC) FROM t",
            "SELECT a, SUM(b) OVER (PARTITION BY c ORDER BY d) FROM t",
            "SELECT a, LAG(a, 1) OVER (ORDER BY a) FROM t",
            "SELECT a, LEAD(a, 1) OVER (ORDER BY a) FROM t",
            "SELECT a, FIRST_VALUE(a) OVER (ORDER BY a) FROM t",
            "SELECT a, LAST_VALUE(a) OVER (ORDER BY a) FROM t",
            "SELECT a, NTILE(4) OVER (ORDER BY a) FROM t",
            "SELECT a, SUM(b) OVER (ORDER BY a ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) FROM t",
            "SELECT a, SUM(b) OVER (ORDER BY a ROWS BETWEEN 1 PRECEDING AND 1 FOLLOWING) FROM t",
            "SELECT a, SUM(b) OVER (ORDER BY a RANGE BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) FROM t",
            "SELECT a, COUNT(*) OVER () FROM t",

            # CTEs
            "WITH cte AS (SELECT a FROM t) SELECT * FROM cte",
            "WITH cte1 AS (SELECT a FROM t1), cte2 AS (SELECT b FROM t2) SELECT * FROM cte1 JOIN cte2 ON cte1.a = cte2.b",
            "WITH RECURSIVE cte AS (SELECT 1 AS n UNION ALL SELECT n + 1 FROM cte WHERE n < 10) SELECT * FROM cte",

            # SELECT DISTINCT ON
            "SELECT DISTINCT ON (a) a, b FROM t",

            # Typed literals
            "SELECT DATE '2023-01-01'",
            "SELECT TIMESTAMP '2023-01-01 00:00:00'",
            "SELECT TIME '12:00:00'",
            "SELECT INTERVAL '1' DAY",

            # Complex queries
            "SELECT a FROM t1 WHERE a > (SELECT AVG(b) FROM t2) ORDER BY a LIMIT 5",
            "SELECT 1 + 2 * 3",
            "SELECT (1 + 2) * 3",
            "SELECT a FROM t WHERE a LIKE 'test' ESCAPE '\\'",

            # CREATE VIEW
            "CREATE VIEW v AS SELECT a FROM t",
            "CREATE OR REPLACE VIEW v AS SELECT a FROM t",

            # TRUNCATE
            "TRUNCATE TABLE t",

            # Transactions
            "BEGIN",
            "BEGIN TRANSACTION",
            "COMMIT",
            "ROLLBACK",
            "SAVEPOINT sp1",
            "RELEASE SAVEPOINT sp1",
            "ROLLBACK TO SAVEPOINT sp1",

            # EXPLAIN
            "EXPLAIN SELECT a FROM t",
            "EXPLAIN ANALYZE SELECT a FROM t",

            # SET
            "SET search_path TO public",

            # GRANT / REVOKE
            "GRANT SELECT ON t TO user1",
            "GRANT ALL ON t TO user1",
            "REVOKE SELECT ON t FROM user1",

            # Misc - these may or may not be supported
            "SELECT a FROM t FOR UPDATE",
            "SELECT a FROM t FOR SHARE",
            "SELECT a FROM t WHERE a::INT > 0",
            "SELECT a FROM t TABLESAMPLE BERNOULLI(10)",
            "SELECT ARRAY[1, 2, 3]",
            "SELECT a[1] FROM t",
            "SELECT a FROM t WHERE a SIMILAR TO '%pattern%'",
            "SELECT a FROM t WHERE a ILIKE '%x%'",
            "INSERT INTO t (a) VALUES (1) RETURNING *",
            "UPDATE t SET a = 1 RETURNING *",
            "DELETE FROM t WHERE a = 1 RETURNING *",
            "SELECT a FROM t1, LATERAL (SELECT * FROM t2 WHERE t2.id = t1.id) AS sub",
            "SELECT COUNT(*) FILTER (WHERE a > 0) FROM t",
            "SELECT a, SUM(b) FROM t GROUP BY CUBE (a)",
            "SELECT a, SUM(b) FROM t GROUP BY ROLLUP (a)",
            "DROP TABLE t CASCADE",
            "DROP TABLE t RESTRICT",
            "DROP VIEW v",
            "DROP VIEW IF EXISTS v",
            "START TRANSACTION",
            "ROLLBACK TO sp1",
            "TRUNCATE t",
            "SELECT a FROM t ORDER BY a NULLS FIRST",
            "SELECT a FROM t ORDER BY a DESC NULLS LAST",
            "MERGE INTO t1 USING t2 ON t1.id = t2.id WHEN MATCHED THEN UPDATE SET a = t2.a WHEN NOT MATCHED THEN INSERT (id, a) VALUES (t2.id, t2.a)",
            "INSERT INTO t (a, b) VALUES (1, 2) ON CONFLICT (a) DO UPDATE SET b = 2",
            "INSERT INTO t (a, b) VALUES (1, 2) ON CONFLICT (a) DO NOTHING",
            "ALTER TABLE t ADD CONSTRAINT ck CHECK (a > 0)",
            "ALTER TABLE t DROP CONSTRAINT IF EXISTS pk",
            "ALTER TABLE t ALTER COLUMN a TYPE VARCHAR(100)",
            "CREATE TABLE t (a INT, UNIQUE (a))",
            "CREATE TABLE t (a INT, b INT, FOREIGN KEY (a) REFERENCES other(id))",
            "CREATE TEMPORARY TABLE t (a INT)",
            "CREATE TEMP TABLE t (a INT)",
            "CREATE TABLE t (a DECIMAL(10, 2), b NUMERIC, c BIGINT, d SMALLINT, e REAL, f DOUBLE PRECISION)",
            "CREATE TABLE t (a SERIAL PRIMARY KEY)",
            "CREATE TABLE t (a INTEGER NOT NULL DEFAULT 0 UNIQUE CHECK (a >= 0))",
            "SELECT TRIM(LEADING ' ' FROM a) FROM t",
            "SELECT TRIM(TRAILING ' ' FROM a) FROM t",
            "SELECT TRIM(BOTH ' ' FROM a) FROM t",
            "SELECT SUBSTRING(a, 1, 3) FROM t",
            "SELECT REPLACE(a, 'x', 'y') FROM t",
            "SELECT POSITION('x' IN a) FROM t",
            "SELECT GREATEST(a, b, c) FROM t",
            "SELECT LEAST(a, b, c) FROM t",
            "SELECT CAST(a AS FLOAT) FROM t",
            "SELECT CAST(a AS BOOLEAN) FROM t",
            "SELECT CAST(a AS DATE) FROM t",
            "SELECT CURRENT_TIME",
            "SELECT EXTRACT(YEAR FROM a) FROM t",
            "SELECT EXTRACT(MONTH FROM a) FROM t",
            "SELECT EXTRACT(DAY FROM a) FROM t",
            "SELECT EXTRACT(HOUR FROM a) FROM t",
            "SELECT LAG(a, 1, 0) OVER (ORDER BY a) FROM t",
            "SELECT NTH_VALUE(a, 2) OVER (ORDER BY a) FROM t",
            "SELECT PERCENT_RANK() OVER (ORDER BY a) FROM t",
            "SELECT CUME_DIST() OVER (ORDER BY a) FROM t",
            "SELECT SUM(b) OVER (ORDER BY a ROWS BETWEEN CURRENT ROW AND UNBOUNDED FOLLOWING) FROM t",
            "SELECT SUM(b) OVER w FROM t WINDOW w AS (PARTITION BY c ORDER BY d)",
            "SELECT CONCAT(a, b, c) FROM t",
            "SELECT LEFT(a, 3) FROM t",
            "SELECT RIGHT(a, 3) FROM t",
            "SELECT LPAD(a, 10, ' ') FROM t",
            "SELECT RPAD(a, 10, ' ') FROM t",
            "SELECT CEIL(a) FROM t",
            "SELECT FLOOR(a) FROM t",
            "SELECT POWER(a, 2) FROM t",
            "SELECT SQRT(a) FROM t",
            "SELECT MOD(a, b) FROM t",
            "GRANT INSERT, UPDATE ON t TO user1",
            "SELECT a FROM t WHERE a NOT IN (SELECT b FROM t2)",
            "SELECT a FROM t1 JOIN t2 USING (id, name)",
            "ALTER TABLE t ADD a INT",
            "SELECT a FROM t FETCH FIRST 5 ROWS ONLY",
            'SELECT "column" FROM "table"',
            "SELECT a FROM t1, t2 WHERE t1.id = t2.id",
            "SELECT 'it''s'",
        ]
