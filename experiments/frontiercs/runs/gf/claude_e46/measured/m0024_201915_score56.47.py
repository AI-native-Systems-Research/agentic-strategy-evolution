import os
import re

class Solution:
    def solve(self, resources_path: str) -> list[str]:
        parser_src = self._read(os.path.join(resources_path, "sql_engine", "parser.py"))
        tokenizer_src = self._read(os.path.join(resources_path, "sql_engine", "tokenizer.py"))

        stmts = list(self._minimal_stmts())

        if parser_src:
            extras = self._extras(parser_src, tokenizer_src)
            seen = set(stmts)
            for s in extras:
                if s not in seen:
                    stmts.append(s)
                    seen.add(s)

        return stmts

    def _read(self, path):
        try:
            with open(path) as f:
                return f.read()
        except Exception:
            return ""

    def _extras(self, parser_src, tokenizer_src):
        extras = []
        src = parser_src + "\n" + tokenizer_src

        kw_stmts = {
            'ILIKE': "SELECT a FROM t WHERE a ILIKE '%x%'",
            'SIMILAR': "SELECT a FROM t WHERE a SIMILAR TO '%x%'",
            'GLOB': "SELECT a FROM t WHERE a GLOB '*x*'",
            'REGEXP': "SELECT a FROM t WHERE a REGEXP '^x'",
            'RETURNING': "INSERT INTO t (a) VALUES (1) RETURNING *",
            'CONFLICT': "INSERT INTO t (a) VALUES (1) ON CONFLICT (a) DO NOTHING",
            'MERGE': "MERGE INTO t1 USING t2 ON t1.id = t2.id WHEN MATCHED THEN UPDATE SET a = t2.a WHEN NOT MATCHED THEN INSERT (a) VALUES (t2.a)",
            'LATERAL': "SELECT * FROM t1, LATERAL (SELECT * FROM t2 WHERE t2.id = t1.id) AS sub",
            'CUBE': "SELECT a, b, SUM(c) FROM t GROUP BY CUBE (a, b)",
            'ROLLUP': "SELECT a, b, SUM(c) FROM t GROUP BY ROLLUP (a, b)",
            'GROUPING': "SELECT a, SUM(b) FROM t GROUP BY GROUPING SETS ((a), ())",
            'FETCH': "SELECT a FROM t ORDER BY a FETCH FIRST 5 ROWS ONLY",
            'FILTER': "SELECT COUNT(*) FILTER (WHERE a > 0) FROM t",
            'WINDOW': "SELECT a, SUM(b) OVER w FROM t WINDOW w AS (ORDER BY a)",
            'NULLS': "SELECT a FROM t ORDER BY a NULLS FIRST",
            'CONCURRENTLY': "CREATE INDEX CONCURRENTLY idx ON t (a)",
            'MATERIALIZED': "CREATE MATERIALIZED VIEW mv AS SELECT a FROM t",
            'REPLACE': "REPLACE INTO t (a) VALUES (1)",
            'SERIAL': "CREATE TABLE t (a SERIAL PRIMARY KEY)",
            'CASCADE': "DROP TABLE t CASCADE",
            'RESTRICT': "DROP TABLE t RESTRICT",
            'TEMP': "CREATE TEMP TABLE t (a INT)",
            'TEMPORARY': "CREATE TEMPORARY TABLE t (a INT)",
            'GENERATED': "CREATE TABLE t (a INT GENERATED ALWAYS AS IDENTITY)",
            'SHOW': "SHOW search_path",
            'RESET': "RESET search_path",
            'VACUUM': "VACUUM t",
            'COPY': "COPY t TO STDOUT",
            'LISTEN': "LISTEN channel1",
            'NOTIFY': "NOTIFY channel1",
            'DISCARD': "DISCARD ALL",
            'PREPARE': "PREPARE stmt AS SELECT a FROM t WHERE a = $1",
            'EXECUTE': "EXECUTE stmt",
            'LOCK': "LOCK TABLE t",
            'COMMENT': "COMMENT ON TABLE t IS 'test'",
            'SCHEMA': "CREATE SCHEMA s",
            'REINDEX': "REINDEX TABLE t",
            'POSITION': "SELECT POSITION('x' IN a) FROM t",
            'EXTRACT': "SELECT EXTRACT(YEAR FROM d) FROM t",
            'OVERLAY': "SELECT OVERLAY(a PLACING 'x' FROM 1 FOR 2) FROM t",
            'GREATEST': "SELECT GREATEST(1, 2, 3)",
            'LEAST': "SELECT LEAST(1, 2, 3)",
            'GROUPS': "SELECT SUM(b) OVER (ORDER BY a GROUPS BETWEEN 1 PRECEDING AND 1 FOLLOWING) FROM t",
            'DO': "DO $$ BEGIN NULL; END $$",
            'ARRAY': "SELECT ARRAY[1, 2, 3]",
            'ROW': "SELECT ROW(1, 2, 3)",
        }

        for kw, stmt in kw_stmts.items():
            if kw in src:
                extras.append(stmt)

        return extras

    def _minimal_stmts(self):
        return [
            # SELECT basics
            "SELECT 1",
            "SELECT a, b, c FROM t",
            "SELECT * FROM t",
            "SELECT DISTINCT a FROM t",
            "SELECT ALL a FROM t",
            "SELECT a AS x FROM t AS z",
            "SELECT t.a, t.* FROM t",

            # WHERE operators (each tests different parser branch)
            "SELECT a FROM t WHERE a = 1",
            "SELECT a FROM t WHERE a != 1",
            "SELECT a FROM t WHERE a <> 1",
            "SELECT a FROM t WHERE a > 1",
            "SELECT a FROM t WHERE a < 1",
            "SELECT a FROM t WHERE a >= 1",
            "SELECT a FROM t WHERE a <= 1",
            "SELECT a FROM t WHERE a LIKE '%test%'",
            "SELECT a FROM t WHERE a NOT LIKE 'x%'",
            "SELECT a FROM t WHERE a IN (1, 2, 3)",
            "SELECT a FROM t WHERE a NOT IN (1, 2)",
            "SELECT a FROM t WHERE a BETWEEN 1 AND 10",
            "SELECT a FROM t WHERE a NOT BETWEEN 1 AND 10",
            "SELECT a FROM t WHERE a IS NULL",
            "SELECT a FROM t WHERE a IS NOT NULL",
            "SELECT a FROM t WHERE a LIKE '%x%' ESCAPE '\\'",

            # Logical operators
            "SELECT a FROM t WHERE a = 1 AND b = 2",
            "SELECT a FROM t WHERE a = 1 OR b = 2",
            "SELECT a FROM t WHERE NOT a = 1",
            "SELECT a FROM t WHERE (a = 1 OR b = 2) AND c = 3",

            # Expressions
            "SELECT a + b, a - b, a * b, a / b, a % b, -a, +a FROM t",
            "SELECT 'hello', 3.14, -3.14, 0, TRUE, FALSE, NULL",
            "SELECT a || b FROM t",
            "SELECT (1 + 2) * 3",

            # Aggregates + GROUP BY + HAVING
            "SELECT COUNT(*), COUNT(a), COUNT(DISTINCT a), SUM(a), AVG(a), MIN(a), MAX(a) FROM t",
            "SELECT a, COUNT(*) FROM t GROUP BY a HAVING COUNT(*) > 1",
            "SELECT a, b, SUM(c) FROM t GROUP BY a, b",

            # ORDER BY + LIMIT
            "SELECT a FROM t ORDER BY a ASC, b DESC",
            "SELECT a FROM t ORDER BY 1",
            "SELECT a FROM t LIMIT 10 OFFSET 5",

            # JOINs (each type is a separate branch)
            "SELECT a FROM t1 JOIN t2 ON t1.id = t2.id",
            "SELECT a FROM t1 LEFT JOIN t2 ON t1.id = t2.id",
            "SELECT a FROM t1 LEFT OUTER JOIN t2 ON t1.id = t2.id",
            "SELECT a FROM t1 RIGHT JOIN t2 ON t1.id = t2.id",
            "SELECT a FROM t1 RIGHT OUTER JOIN t2 ON t1.id = t2.id",
            "SELECT a FROM t1 FULL JOIN t2 ON t1.id = t2.id",
            "SELECT a FROM t1 FULL OUTER JOIN t2 ON t1.id = t2.id",
            "SELECT a FROM t1 CROSS JOIN t2",
            "SELECT a FROM t1 NATURAL JOIN t2",
            "SELECT a FROM t1 JOIN t2 USING (id)",

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

            # UPDATE + DELETE
            "UPDATE t SET a = 1, b = 2 WHERE c = 3",
            "DELETE FROM t WHERE a = 1",
            "DELETE FROM t",

            # CREATE TABLE
            "CREATE TABLE t (a INT PRIMARY KEY, b VARCHAR(255) NOT NULL, c FLOAT DEFAULT 0.0, d BOOLEAN, e DATE, f TIMESTAMP, g TEXT UNIQUE)",
            "CREATE TABLE IF NOT EXISTS t (a INT)",
            "CREATE TABLE t (a INT, b INT, PRIMARY KEY (a, b))",
            "CREATE TABLE t (a INT REFERENCES other(id))",
            "CREATE TABLE t (a INT CHECK (a > 0))",
            "CREATE TABLE t (a DECIMAL(10, 2), b INTEGER, c REAL, d CHAR(10), e VARCHAR(100))",

            # DROP
            "DROP TABLE t",
            "DROP TABLE IF EXISTS t",

            # INDEX
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
            "SELECT UPPER(a), LOWER(a), LENGTH(a), TRIM(a) FROM t",
            "SELECT SUBSTRING(a FROM 1 FOR 3) FROM t",
            "SELECT SUBSTR(a, 1, 3) FROM t",
            "SELECT COALESCE(a, b, c), NULLIF(a, b) FROM t",
            "SELECT CAST(a AS INT), CAST(b AS VARCHAR(100)) FROM t",
            "SELECT ABS(a), ROUND(a, 2), CONCAT(a, b) FROM t",
            "SELECT NOW(), CURRENT_TIMESTAMP, CURRENT_DATE",
            "SELECT TRIM(LEADING 'x' FROM a), TRIM(TRAILING 'x' FROM a), TRIM(BOTH 'x' FROM a) FROM t",

            # Window functions
            "SELECT ROW_NUMBER() OVER (ORDER BY a), RANK() OVER (PARTITION BY b ORDER BY a), DENSE_RANK() OVER (ORDER BY a DESC) FROM t",
            "SELECT SUM(b) OVER (PARTITION BY c ORDER BY d) FROM t",
            "SELECT LAG(a, 1) OVER (ORDER BY a), LEAD(a, 1) OVER (ORDER BY a) FROM t",
            "SELECT FIRST_VALUE(a) OVER (ORDER BY a), LAST_VALUE(a) OVER (ORDER BY a) FROM t",
            "SELECT NTILE(4) OVER (ORDER BY a) FROM t",
            "SELECT SUM(b) OVER (ORDER BY a ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) FROM t",
            "SELECT SUM(b) OVER (ORDER BY a ROWS BETWEEN 1 PRECEDING AND 1 FOLLOWING) FROM t",
            "SELECT SUM(b) OVER (ORDER BY a RANGE BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) FROM t",
            "SELECT COUNT(*) OVER () FROM t",

            # CTEs
            "WITH cte AS (SELECT a FROM t) SELECT * FROM cte",
            "WITH cte1 AS (SELECT a FROM t1), cte2 AS (SELECT b FROM t2) SELECT * FROM cte1 JOIN cte2 ON cte1.a = cte2.b",
            "WITH RECURSIVE cte AS (SELECT 1 AS n UNION ALL SELECT n + 1 FROM cte WHERE n < 10) SELECT * FROM cte",

            # Misc SELECT features
            "SELECT DISTINCT ON (a) a, b FROM t",
            "SELECT DATE '2023-01-01'",
            "SELECT TIMESTAMP '2023-01-01 00:00:00'",
            "SELECT TIME '12:00:00'",
            "SELECT INTERVAL '1' DAY",

            # VIEW
            "CREATE VIEW v AS SELECT a FROM t",
            "CREATE OR REPLACE VIEW v AS SELECT a FROM t",

            # Transaction control
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

            # Locking / TRUNCATE
            "SELECT a FROM t FOR UPDATE",
            "SELECT a FROM t FOR SHARE",
            "TRUNCATE TABLE t",

            # Type casting
            "SELECT a::INT FROM t",
        ]
