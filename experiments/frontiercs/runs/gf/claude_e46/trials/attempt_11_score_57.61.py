import os
import re

class Solution:
    def solve(self, resources_path: str) -> list[str]:
        parser_src = self._read(os.path.join(resources_path, "sql_engine", "parser.py"))
        tokenizer_src = self._read(os.path.join(resources_path, "sql_engine", "tokenizer.py"))

        stmts = list(self._base_stmts())

        if parser_src:
            extras = self._extras_from_parser(parser_src, tokenizer_src)
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

    def _extras_from_parser(self, parser_src, tokenizer_src):
        extras = []
        src = parser_src + tokenizer_src

        if 'ILIKE' in src:
            extras.append("SELECT a FROM t WHERE a ILIKE '%x%'")
        if 'RETURNING' in src:
            extras.extend([
                "INSERT INTO t (a) VALUES (1) RETURNING *",
                "UPDATE t SET a = 1 RETURNING *",
                "DELETE FROM t RETURNING *",
            ])
        if 'LATERAL' in src:
            extras.append("SELECT a FROM t1, LATERAL (SELECT * FROM t2 WHERE t2.id = t1.id) AS sub")
        if 'FILTER' in src:
            extras.append("SELECT COUNT(*) FILTER (WHERE a > 0) FROM t")
        if 'CUBE' in src:
            extras.append("SELECT a, SUM(b) FROM t GROUP BY CUBE (a)")
        if 'ROLLUP' in src:
            extras.append("SELECT a, SUM(b) FROM t GROUP BY ROLLUP (a)")
        if 'GROUPING' in src and 'SETS' in src:
            extras.append("SELECT a, SUM(b) FROM t GROUP BY GROUPING SETS ((a), ())")
        if 'CASCADE' in src:
            extras.append("DROP TABLE t CASCADE")
        if 'RESTRICT' in src:
            extras.append("DROP TABLE t RESTRICT")
        if 'NULLS' in src:
            extras.extend([
                "SELECT a FROM t ORDER BY a NULLS FIRST",
                "SELECT a FROM t ORDER BY a DESC NULLS LAST",
            ])
        if 'CONFLICT' in src:
            extras.extend([
                "INSERT INTO t (a) VALUES (1) ON CONFLICT (a) DO NOTHING",
                "INSERT INTO t (a) VALUES (1) ON CONFLICT (a) DO UPDATE SET a = 2",
            ])
        if 'MERGE' in src:
            extras.append("MERGE INTO t1 USING t2 ON t1.id = t2.id WHEN MATCHED THEN UPDATE SET a = t2.a WHEN NOT MATCHED THEN INSERT (a) VALUES (t2.a)")
        if 'WINDOW' in src:
            extras.append("SELECT SUM(b) OVER w FROM t WINDOW w AS (PARTITION BY c ORDER BY d)")
        extras.append("SELECT SUM(b) OVER (ORDER BY a ROWS BETWEEN CURRENT ROW AND UNBOUNDED FOLLOWING) FROM t")
        if 'GREATEST' in src:
            extras.append("SELECT GREATEST(a, b, c) FROM t")
        if 'LEAST' in src:
            extras.append("SELECT LEAST(a, b, c) FROM t")
        if 'REPLACE' in src and 'REPLACE' in parser_src:
            extras.append("SELECT REPLACE(a, 'x', 'y') FROM t")
        if 'POSITION' in src:
            extras.append("SELECT POSITION('x' IN a) FROM t")
        if 'LEADING' in src:
            extras.append("SELECT TRIM(LEADING ' ' FROM a) FROM t")
        if 'TRAILING' in src:
            extras.append("SELECT TRIM(TRAILING ' ' FROM a) FROM t")
        if 'BOTH' in src:
            extras.append("SELECT TRIM(BOTH ' ' FROM a) FROM t")
        if 'EXTRACT' in src:
            extras.extend([
                "SELECT EXTRACT(YEAR FROM a) FROM t",
                "SELECT EXTRACT(MONTH FROM a) FROM t",
                "SELECT EXTRACT(DAY FROM a) FROM t",
                "SELECT EXTRACT(HOUR FROM a) FROM t",
            ])
        if 'CURRENT_TIME' in src and 'CURRENT_TIMESTAMP' not in 'CURRENT_TIME':
            extras.append("SELECT CURRENT_TIME")
        if 'CAST' in src:
            extras.extend([
                "SELECT CAST(a AS FLOAT) FROM t",
                "SELECT CAST(a AS BOOLEAN) FROM t",
                "SELECT CAST(a AS DATE) FROM t",
            ])
        if '::' in parser_src:
            extras.extend(["SELECT a::INT FROM t", "SELECT a::TEXT FROM t"])
        if 'LAG' in src:
            extras.append("SELECT LAG(a, 1, 0) OVER (ORDER BY a) FROM t")
        if 'NTH_VALUE' in src:
            extras.append("SELECT NTH_VALUE(a, 2) OVER (ORDER BY a) FROM t")
        if 'PERCENT_RANK' in src:
            extras.append("SELECT PERCENT_RANK() OVER (ORDER BY a) FROM t")
        if 'CUME_DIST' in src:
            extras.append("SELECT CUME_DIST() OVER (ORDER BY a) FROM t")
        if 'TYPE' in src and 'ALTER' in src:
            extras.append("ALTER TABLE t ALTER COLUMN a TYPE VARCHAR(100)")
        if 'CHECK' in parser_src:
            extras.append("ALTER TABLE t ADD CONSTRAINT ck CHECK (a > 0)")
        if 'CONSTRAINT' in src:
            extras.append("ALTER TABLE t DROP CONSTRAINT IF EXISTS pk")
        if 'UNIQUE' in src:
            extras.append("CREATE TABLE tu (a INT, UNIQUE (a))")
        if 'FOREIGN' in src:
            extras.append("CREATE TABLE tfk (a INT, FOREIGN KEY (a) REFERENCES other(id))")
        if 'NUMERIC' in src or 'BIGINT' in src:
            extras.append("CREATE TABLE tn (a NUMERIC, b BIGINT, c SMALLINT, d DOUBLE PRECISION)")
        if 'SERIAL' in src:
            extras.append("CREATE TABLE ts (a SERIAL PRIMARY KEY)")
        if 'TEMPORARY' in src or 'TEMP' in src:
            extras.extend([
                "CREATE TEMPORARY TABLE tmp (a INT)",
                "CREATE TEMP TABLE tmp2 (a INT)",
            ])
        if re.search(r'SCHEMA', parser_src):
            extras.extend(["CREATE SCHEMA myschema", "DROP SCHEMA myschema"])
        if re.search(r'DATABASE', parser_src):
            extras.extend(["CREATE DATABASE mydb", "DROP DATABASE mydb"])
        if 'SEQUENCE' in parser_src:
            extras.extend(["CREATE SEQUENCE myseq", "DROP SEQUENCE myseq"])
        if 'TABLESAMPLE' in src:
            extras.append("SELECT a FROM t TABLESAMPLE BERNOULLI(10)")
        if 'FETCH' in parser_src and 'FIRST' in parser_src:
            extras.append("SELECT a FROM t FETCH FIRST 5 ROWS ONLY")
        if re.search(r'\bSHOW\b', parser_src):
            extras.append("SHOW ALL")
        if 'VACUUM' in parser_src:
            extras.append("VACUUM")
        if re.search(r'parse_analyze', parser_src):
            extras.append("ANALYZE t")
        if 'PREPARE' in parser_src:
            extras.append("PREPARE stmt AS SELECT 1")
        if re.search(r'parse_execute', parser_src):
            extras.append("EXECUTE stmt")
        if 'DECLARE' in parser_src:
            extras.append("DECLARE cur CURSOR FOR SELECT a FROM t")
        if re.search(r'\bCLOSE\b', parser_src):
            extras.append("CLOSE cur")
        if re.search(r'\bLOCK\b', parser_src):
            extras.append("LOCK TABLE t")
        if 'LISTEN' in parser_src:
            extras.append("LISTEN ch")
        if 'NOTIFY' in parser_src:
            extras.append("NOTIFY ch")
        if re.search(r'\bCOPY\b', parser_src):
            extras.append("COPY t FROM 'file.csv'")
        if re.search(r'\bCOMMENT\b', parser_src):
            extras.append("COMMENT ON TABLE t IS 'desc'")
        if 'ON DELETE' in parser_src or 'on_delete' in parser_src:
            extras.extend([
                "CREATE TABLE fk1 (a INT REFERENCES other(id) ON DELETE CASCADE)",
                "CREATE TABLE fk2 (a INT REFERENCES other(id) ON DELETE SET NULL)",
                "CREATE TABLE fk3 (a INT REFERENCES other(id) ON UPDATE CASCADE)",
            ])
        if 'SIMILAR' in parser_src:
            extras.append("SELECT a FROM t WHERE a SIMILAR TO '%x%'")
        if 'ARRAY' in src:
            extras.extend(["SELECT ARRAY[1, 2, 3]", "SELECT a[1] FROM t"])

        extras.extend([
            'SELECT "col" FROM "tbl"',
            "SELECT 'it''s'",
            "SELECT a FROM t1, t2 WHERE t1.id = t2.id",
            "ALTER TABLE t ADD a INT",
            "SELECT a FROM t WHERE a NOT IN (SELECT b FROM t2)",
            "SELECT a FROM t1 JOIN t2 USING (id, name)",
            "CREATE TABLE tc (a INTEGER NOT NULL DEFAULT 0 UNIQUE CHECK (a >= 0))",
            "DROP VIEW v",
            "DROP VIEW IF EXISTS v",
            "START TRANSACTION",
            "ROLLBACK TO sp1",
            "TRUNCATE t",
            "SELECT a FROM t OFFSET 5",
            "GRANT INSERT, UPDATE ON t TO user1",
            "SELECT CURRENT_TIME",
            "INSERT INTO t DEFAULT VALUES",
        ])

        return extras

    def _base_stmts(self):
        return [
            # SELECT core - consolidated
            "SELECT 1",
            "SELECT a, b, c FROM t",
            "SELECT * FROM t",
            "SELECT DISTINCT a FROM t",
            "SELECT ALL a FROM t",
            "SELECT a AS x, b AS y FROM t AS z",
            "SELECT t.a, t.* FROM t",

            # WHERE: all comparison ops as separate stmts (each triggers different branch)
            "SELECT a FROM t WHERE a = 1",
            "SELECT a FROM t WHERE a != 1",
            "SELECT a FROM t WHERE a <> 1",
            "SELECT a FROM t WHERE a > 1",
            "SELECT a FROM t WHERE a < 1",
            "SELECT a FROM t WHERE a >= 1",
            "SELECT a FROM t WHERE a <= 1",

            # WHERE: special ops
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

            # Arithmetic + literals (consolidated)
            "SELECT a + b, a - b, a * b, a / b, a % b, -a, +a FROM t",
            "SELECT 'hello', 3.14, -3.14, 0, TRUE, FALSE, NULL",
            "SELECT a || b FROM t",
            "SELECT (1 + 2) * 3",

            # Aggregates (consolidated)
            "SELECT COUNT(*), COUNT(a), COUNT(DISTINCT a), SUM(a), AVG(a), MIN(a), MAX(a) FROM t",

            # GROUP BY / HAVING
            "SELECT a, COUNT(*) FROM t GROUP BY a HAVING COUNT(*) > 1",
            "SELECT a, b, SUM(c) FROM t GROUP BY a, b",

            # ORDER BY
            "SELECT a FROM t ORDER BY a ASC, b DESC",
            "SELECT a FROM t ORDER BY 1",

            # LIMIT / OFFSET
            "SELECT a FROM t LIMIT 10 OFFSET 5",

            # JOINs - each type must be separate
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

            # UPDATE / DELETE
            "UPDATE t SET a = 1, b = 2 WHERE c = 3",
            "DELETE FROM t WHERE a = 1",
            "DELETE FROM t",

            # CREATE TABLE (consolidated types)
            "CREATE TABLE t (a INT PRIMARY KEY, b VARCHAR(255) NOT NULL, c FLOAT DEFAULT 0.0, d BOOLEAN, e DATE, f TIMESTAMP, g TEXT UNIQUE)",
            "CREATE TABLE IF NOT EXISTS t (a INT)",
            "CREATE TABLE t (a INT, b INT, PRIMARY KEY (a, b))",
            "CREATE TABLE t (a INT REFERENCES other(id))",
            "CREATE TABLE t (a INT CHECK (a > 0))",
            "CREATE TABLE t (a DECIMAL(10, 2), b INTEGER, c REAL, d CHAR(10), e VARCHAR(100))",

            # DROP TABLE
            "DROP TABLE t",
            "DROP TABLE IF EXISTS t",

            # CREATE/DROP Index
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

            # Functions (consolidated)
            "SELECT UPPER(a), LOWER(a), LENGTH(a), TRIM(a) FROM t",
            "SELECT SUBSTRING(a FROM 1 FOR 3) FROM t",
            "SELECT SUBSTR(a, 1, 3) FROM t",
            "SELECT COALESCE(a, b, c), NULLIF(a, b) FROM t",
            "SELECT CAST(a AS INT), CAST(b AS VARCHAR(100)) FROM t",
            "SELECT ABS(a), ROUND(a, 2), CONCAT(a, b) FROM t",
            "SELECT NOW(), CURRENT_TIMESTAMP, CURRENT_DATE",

            # Window functions (consolidated where possible)
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

            # DISTINCT ON
            "SELECT DISTINCT ON (a) a, b FROM t",

            # Typed literals
            "SELECT DATE '2023-01-01'",
            "SELECT TIMESTAMP '2023-01-01 00:00:00'",
            "SELECT TIME '12:00:00'",
            "SELECT INTERVAL '1' DAY",

            # Complex
            "SELECT a FROM t1 WHERE a > (SELECT AVG(b) FROM t2) ORDER BY a LIMIT 5",

            # CREATE/DROP View
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

            # FOR UPDATE/SHARE
            "SELECT a FROM t FOR UPDATE",
            "SELECT a FROM t FOR SHARE",
        ]
