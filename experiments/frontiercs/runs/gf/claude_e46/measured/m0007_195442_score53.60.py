import os
import re

class Solution:
    def solve(self, resources_path: str) -> list[str]:
        parser_src = self._read(os.path.join(resources_path, "sql_engine", "parser.py"))
        tokenizer_src = self._read(os.path.join(resources_path, "sql_engine", "tokenizer.py"))
        grammar_src = self._read(os.path.join(resources_path, "sql_grammar.txt"))

        stmts = self._build_corpus(parser_src, tokenizer_src, grammar_src)
        return stmts

    def _read(self, path):
        try:
            with open(path) as f:
                return f.read()
        except:
            return ""

    def _build_corpus(self, parser_src, tokenizer_src, grammar_src):
        stmts = [
            # Core SELECT
            "SELECT 1",
            "SELECT a, b FROM t",
            "SELECT * FROM t",
            "SELECT DISTINCT a FROM t",
            "SELECT ALL a FROM t",
            "SELECT a AS x FROM t AS y",
            "SELECT t.a FROM t",
            "SELECT t.* FROM t",

            # WHERE
            "SELECT a FROM t WHERE a = 1",
            "SELECT a FROM t WHERE a != 1",
            "SELECT a FROM t WHERE a <> 1",
            "SELECT a FROM t WHERE a > 1",
            "SELECT a FROM t WHERE a < 1",
            "SELECT a FROM t WHERE a >= 1",
            "SELECT a FROM t WHERE a <= 1",
            "SELECT a FROM t WHERE a LIKE '%x%'",
            "SELECT a FROM t WHERE a NOT LIKE 'x%'",
            "SELECT a FROM t WHERE a IN (1, 2, 3)",
            "SELECT a FROM t WHERE a NOT IN (1, 2)",
            "SELECT a FROM t WHERE a BETWEEN 1 AND 10",
            "SELECT a FROM t WHERE a NOT BETWEEN 1 AND 10",
            "SELECT a FROM t WHERE a IS NULL",
            "SELECT a FROM t WHERE a IS NOT NULL",
            "SELECT a FROM t WHERE a = 1 AND b = 2",
            "SELECT a FROM t WHERE a = 1 OR b = 2",
            "SELECT a FROM t WHERE NOT a = 1",
            "SELECT a FROM t WHERE (a = 1 OR b = 2) AND c = 3",

            # Arithmetic and string
            "SELECT a + b, a - b, a * b, a / b, a % b FROM t",
            "SELECT -a FROM t",
            "SELECT (1 + 2) * 3",
            "SELECT a || b FROM t",

            # Literals
            "SELECT 'hello', 3.14, -42, TRUE, FALSE, NULL",

            # Aggregates + GROUP BY + HAVING
            "SELECT COUNT(*), COUNT(a), COUNT(DISTINCT a), SUM(a), AVG(a), MIN(a), MAX(a) FROM t GROUP BY a HAVING COUNT(*) > 1",

            # ORDER BY
            "SELECT a FROM t ORDER BY a ASC, b DESC",
            "SELECT a FROM t ORDER BY a NULLS FIRST",
            "SELECT a FROM t ORDER BY a DESC NULLS LAST",

            # LIMIT / OFFSET
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
            "SELECT a FROM t1 JOIN t2 USING (id, name)",

            # Subqueries
            "SELECT a FROM (SELECT b FROM t) AS sub",
            "SELECT a FROM t WHERE a IN (SELECT b FROM t2)",
            "SELECT a FROM t WHERE EXISTS (SELECT 1 FROM t2 WHERE t2.id = t.id)",
            "SELECT a FROM t WHERE NOT EXISTS (SELECT 1 FROM t2)",
            "SELECT (SELECT MAX(a) FROM t2) FROM t",
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

            # UPDATE / DELETE
            "UPDATE t SET a = 1, b = 2 WHERE c = 3",
            "DELETE FROM t WHERE a = 1",
            "DELETE FROM t",

            # CREATE TABLE
            "CREATE TABLE t (a INT PRIMARY KEY, b VARCHAR(255) NOT NULL, c FLOAT DEFAULT 0.0, d BOOLEAN, e DATE, f TIMESTAMP, g TEXT UNIQUE)",
            "CREATE TABLE IF NOT EXISTS t (a INT)",
            "CREATE TABLE t (a INT, b INT, PRIMARY KEY (a, b))",
            "CREATE TABLE t (a INT REFERENCES other(id))",
            "CREATE TABLE t (a INT CHECK (a > 0))",
            "CREATE TABLE t (a DECIMAL(10, 2), b NUMERIC, c BIGINT, d SMALLINT, e REAL, f DOUBLE PRECISION)",
            "CREATE TABLE t (a INT, UNIQUE (a))",
            "CREATE TABLE t (a INT, b INT, FOREIGN KEY (a) REFERENCES other(id))",
            "CREATE TABLE t (a SERIAL PRIMARY KEY)",
            "CREATE TABLE t (a CHAR(10), b INTEGER)",
            "CREATE TABLE t (a INTEGER NOT NULL DEFAULT 0 UNIQUE CHECK (a >= 0))",
            "CREATE TEMPORARY TABLE t (a INT)",
            "CREATE TEMP TABLE t (a INT)",

            # DROP TABLE
            "DROP TABLE t",
            "DROP TABLE IF EXISTS t",
            "DROP TABLE t CASCADE",
            "DROP TABLE t RESTRICT",

            # CREATE/DROP INDEX
            "CREATE INDEX idx ON t (a)",
            "CREATE UNIQUE INDEX idx ON t (a, b)",
            "CREATE INDEX IF NOT EXISTS idx ON t (a)",
            "DROP INDEX idx",
            "DROP INDEX IF EXISTS idx",

            # ALTER TABLE
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

            # CASE
            "SELECT CASE WHEN a = 1 THEN 'one' WHEN a = 2 THEN 'two' ELSE 'other' END FROM t",
            "SELECT CASE a WHEN 1 THEN 'one' WHEN 2 THEN 'two' END FROM t",

            # Functions
            "SELECT UPPER(a), LOWER(a), LENGTH(a), TRIM(a), ABS(a), ROUND(a, 2) FROM t",
            "SELECT TRIM(LEADING ' ' FROM a) FROM t",
            "SELECT TRIM(TRAILING ' ' FROM a) FROM t",
            "SELECT TRIM(BOTH ' ' FROM a) FROM t",
            "SELECT SUBSTRING(a FROM 1 FOR 3) FROM t",
            "SELECT SUBSTRING(a, 1, 3) FROM t",
            "SELECT REPLACE(a, 'x', 'y') FROM t",
            "SELECT POSITION('x' IN a) FROM t",
            "SELECT COALESCE(a, b, c) FROM t",
            "SELECT NULLIF(a, b) FROM t",
            "SELECT GREATEST(a, b, c) FROM t",
            "SELECT LEAST(a, b, c) FROM t",
            "SELECT CAST(a AS INT) FROM t",
            "SELECT CAST(a AS VARCHAR(100)) FROM t",
            "SELECT a::INT FROM t",
            "SELECT CONCAT(a, b, c) FROM t",
            "SELECT LEFT(a, 3), RIGHT(a, 3) FROM t",
            "SELECT NOW()",
            "SELECT CURRENT_TIMESTAMP",
            "SELECT CURRENT_DATE",
            "SELECT CURRENT_TIME",
            "SELECT EXTRACT(YEAR FROM a) FROM t",
            "SELECT EXTRACT(MONTH FROM a) FROM t",

            # Window functions
            "SELECT ROW_NUMBER() OVER (ORDER BY a), RANK() OVER (PARTITION BY b ORDER BY a), DENSE_RANK() OVER (ORDER BY a) FROM t",
            "SELECT LAG(a, 1) OVER (ORDER BY a), LEAD(a, 1) OVER (ORDER BY a) FROM t",
            "SELECT LAG(a, 1, 0) OVER (ORDER BY a) FROM t",
            "SELECT FIRST_VALUE(a) OVER (ORDER BY a), LAST_VALUE(a) OVER (ORDER BY a) FROM t",
            "SELECT NTH_VALUE(a, 2) OVER (ORDER BY a) FROM t",
            "SELECT NTILE(4) OVER (ORDER BY a) FROM t",
            "SELECT PERCENT_RANK() OVER (ORDER BY a), CUME_DIST() OVER (ORDER BY a) FROM t",
            "SELECT SUM(b) OVER (ORDER BY a ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) FROM t",
            "SELECT SUM(b) OVER (ORDER BY a ROWS BETWEEN 1 PRECEDING AND 1 FOLLOWING) FROM t",
            "SELECT SUM(b) OVER (ORDER BY a RANGE BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) FROM t",
            "SELECT SUM(b) OVER (ORDER BY a ROWS BETWEEN CURRENT ROW AND UNBOUNDED FOLLOWING) FROM t",
            "SELECT COUNT(*) OVER () FROM t",
            "SELECT SUM(b) OVER w FROM t WINDOW w AS (PARTITION BY c ORDER BY d)",

            # CTEs
            "WITH cte AS (SELECT a FROM t) SELECT * FROM cte",
            "WITH cte1 AS (SELECT a FROM t1), cte2 AS (SELECT b FROM t2) SELECT * FROM cte1 JOIN cte2 ON cte1.a = cte2.b",
            "WITH RECURSIVE cte AS (SELECT 1 AS n UNION ALL SELECT n + 1 FROM cte WHERE n < 10) SELECT * FROM cte",

            # CREATE/DROP VIEW
            "CREATE VIEW v AS SELECT a FROM t",
            "CREATE OR REPLACE VIEW v AS SELECT a FROM t",
            "DROP VIEW v",
            "DROP VIEW IF EXISTS v",

            # Transactions
            "BEGIN",
            "BEGIN TRANSACTION",
            "START TRANSACTION",
            "COMMIT",
            "ROLLBACK",
            "SAVEPOINT sp1",
            "RELEASE SAVEPOINT sp1",
            "ROLLBACK TO SAVEPOINT sp1",
            "ROLLBACK TO sp1",

            # EXPLAIN
            "EXPLAIN SELECT a FROM t",
            "EXPLAIN ANALYZE SELECT a FROM t",

            # TRUNCATE
            "TRUNCATE TABLE t",
            "TRUNCATE t",

            # GRANT / REVOKE
            "GRANT SELECT ON t TO user1",
            "GRANT ALL ON t TO user1",
            "GRANT INSERT, UPDATE ON t TO user1",
            "REVOKE SELECT ON t FROM user1",

            # UPSERT / MERGE
            "MERGE INTO t1 USING t2 ON t1.id = t2.id WHEN MATCHED THEN UPDATE SET a = t2.a WHEN NOT MATCHED THEN INSERT (id, a) VALUES (t2.id, t2.a)",
            "INSERT INTO t (a, b) VALUES (1, 2) ON CONFLICT (a) DO UPDATE SET b = 2",
            "INSERT INTO t (a, b) VALUES (1, 2) ON CONFLICT (a) DO NOTHING",

            # Typed literals
            "SELECT DATE '2023-01-01'",
            "SELECT TIME '12:00:00'",
            "SELECT TIMESTAMP '2023-01-01 00:00:00'",
            "SELECT INTERVAL '1 day'",

            # Misc
            "SELECT a FROM t FOR UPDATE",
            "SELECT a FROM t FOR SHARE",
            "SET search_path TO public",

            # Additional coverage targets based on dynamic analysis
        ]

        # Dynamically add statements based on parser source analysis
        extra = self._analyze_and_extend(parser_src, tokenizer_src, grammar_src)
        stmts.extend(extra)

        return stmts

    def _analyze_and_extend(self, parser_src, tokenizer_src, grammar_src):
        """Analyze source to find additional SQL constructs to test."""
        extra = []

        # Check for ILIKE
        if 'ILIKE' in parser_src or 'ILIKE' in tokenizer_src:
            extra.append("SELECT a FROM t WHERE a ILIKE '%x%'")

        # RETURNING clause
        if 'RETURNING' in parser_src or 'RETURNING' in tokenizer_src:
            extra.extend([
                "INSERT INTO t (a) VALUES (1) RETURNING *",
                "INSERT INTO t (a) VALUES (1) RETURNING a, b",
                "UPDATE t SET a = 1 RETURNING *",
                "DELETE FROM t WHERE a = 1 RETURNING *",
            ])

        # DISTINCT ON
        if 'DISTINCT' in parser_src and 'ON' in parser_src:
            extra.append("SELECT DISTINCT ON (a) a, b FROM t ORDER BY a")

        # LATERAL
        if 'LATERAL' in parser_src or 'LATERAL' in tokenizer_src:
            extra.append("SELECT a FROM t1, LATERAL (SELECT * FROM t2 WHERE t2.id = t1.id) AS sub")

        # FILTER
        if 'FILTER' in parser_src or 'FILTER' in tokenizer_src:
            extra.append("SELECT COUNT(*) FILTER (WHERE a > 0) FROM t")

        # CUBE / ROLLUP / GROUPING SETS
        if 'CUBE' in parser_src or 'CUBE' in tokenizer_src:
            extra.append("SELECT a, SUM(b) FROM t GROUP BY CUBE (a)")
        if 'ROLLUP' in parser_src or 'ROLLUP' in tokenizer_src:
            extra.append("SELECT a, SUM(b) FROM t GROUP BY ROLLUP (a)")
        if 'GROUPING' in parser_src:
            extra.append("SELECT a, SUM(b) FROM t GROUP BY GROUPING SETS ((a), ())")

        # TABLESAMPLE
        if 'TABLESAMPLE' in parser_src or 'TABLESAMPLE' in tokenizer_src:
            extra.extend([
                "SELECT a FROM t TABLESAMPLE BERNOULLI(10)",
                "SELECT a FROM t TABLESAMPLE SYSTEM(10)",
            ])

        # ARRAY
        if 'ARRAY' in parser_src or 'ARRAY' in tokenizer_src:
            extra.extend(["SELECT ARRAY[1, 2, 3]", "SELECT a[1] FROM t"])

        # FETCH
        if 'FETCH' in parser_src and 'FIRST' in parser_src:
            extra.append("SELECT a FROM t FETCH FIRST 5 ROWS ONLY")

        # VACUUM / ANALYZE commands
        if 'VACUUM' in parser_src:
            extra.append("VACUUM")
        if re.search(r'\bparse_analyze\b', parser_src):
            extra.append("ANALYZE t")

        # SCHEMA
        if 'SCHEMA' in parser_src:
            extra.extend(["CREATE SCHEMA s", "DROP SCHEMA s", "DROP SCHEMA IF EXISTS s CASCADE"])

        # DATABASE
        if re.search(r'\bDATABASE\b', parser_src):
            extra.extend(["CREATE DATABASE d", "DROP DATABASE d", "DROP DATABASE IF EXISTS d"])

        # SEQUENCE
        if 'SEQUENCE' in parser_src:
            extra.extend(["CREATE SEQUENCE seq", "DROP SEQUENCE seq", "CREATE SEQUENCE seq START WITH 1 INCREMENT BY 1"])

        # PREPARE / EXECUTE
        if 'PREPARE' in parser_src:
            extra.append("PREPARE stmt AS SELECT a FROM t WHERE a = $1")
        if re.search(r'\bparse_execute\b', parser_src):
            extra.append("EXECUTE stmt(1)")

        # DEALLOCATE
        if 'DEALLOCATE' in parser_src:
            extra.append("DEALLOCATE stmt")

        # DECLARE cursor
        if 'DECLARE' in parser_src:
            extra.append("DECLARE cur CURSOR FOR SELECT a FROM t")

        # CLOSE
        if re.search(r'\bCLOSE\b', parser_src):
            extra.append("CLOSE cur")

        # LOCK
        if 'LOCK' in parser_src:
            extra.append("LOCK TABLE t")

        # SHOW
        if re.search(r'\bSHOW\b', parser_src):
            extra.append("SHOW ALL")

        # LISTEN / NOTIFY
        if 'LISTEN' in parser_src:
            extra.append("LISTEN channel1")
        if 'NOTIFY' in parser_src:
            extra.append("NOTIFY channel1")

        # COPY
        if 'COPY' in parser_src:
            extra.extend(["COPY t FROM 'file.csv'", "COPY t TO 'file.csv'"])

        # COMMENT
        if 'COMMENT' in parser_src:
            extra.append("COMMENT ON TABLE t IS 'description'")

        # ON DELETE/UPDATE actions for FK
        if 'ON DELETE' in parser_src or 'CASCADE' in parser_src:
            extra.extend([
                "CREATE TABLE t (a INT REFERENCES other(id) ON DELETE CASCADE ON UPDATE SET NULL)",
                "CREATE TABLE t (a INT REFERENCES other(id) ON DELETE SET DEFAULT)",
                "CREATE TABLE t (a INT REFERENCES other(id) ON DELETE RESTRICT)",
                "CREATE TABLE t (a INT REFERENCES other(id) ON DELETE NO ACTION)",
            ])

        # INSERT ... ON CONFLICT ... EXCLUDED
        if 'EXCLUDED' in parser_src:
            extra.append("INSERT INTO t (a) VALUES (1) ON CONFLICT (a) DO UPDATE SET a = EXCLUDED.a RETURNING *")

        # UPDATE ... FROM
        if re.search(r'UPDATE.*FROM', parser_src) or 'parse_update' in parser_src:
            extra.append("UPDATE t SET a = t2.a FROM t2 WHERE t.id = t2.id")

        # DELETE ... USING
        if 'USING' in parser_src:
            extra.append("DELETE FROM t USING t2 WHERE t.id = t2.id")

        # CREATE TABLE AS
        if 'CREATE TABLE' in parser_src and 'AS' in parser_src:
            extra.append("CREATE TABLE t AS SELECT a FROM other")

        # Quoted identifiers
        if '"' in tokenizer_src or 'QUOTED' in tokenizer_src or 'quoted' in tokenizer_src:
            extra.append('SELECT "column" FROM "table"')

        # Escape strings
        if "E'" in tokenizer_src or 'escape' in tokenizer_src.lower():
            extra.append("SELECT E'hello\\nworld'")

        # Numeric formats
        if 'e' in tokenizer_src or 'E' in tokenizer_src or 'exponent' in tokenizer_src.lower():
            extra.append("SELECT 1e10, 1.5e-3")

        # Multiple FROM tables (implicit cross join)
        extra.append("SELECT a, b FROM t1, t2 WHERE t1.id = t2.id")

        # Schema-qualified names
        extra.append("SELECT a FROM schema1.t")

        # Nested CASE
        extra.append("SELECT CASE WHEN a > 0 THEN CASE WHEN b > 0 THEN 'both' ELSE 'a' END ELSE 'none' END FROM t")

        # Deep subquery nesting
        extra.append("SELECT a FROM t WHERE a IN (SELECT b FROM t2 WHERE b IN (SELECT c FROM t3))")

        # String escaping
        extra.append("SELECT 'it''s'")

        # Complex expressions
        extra.append("SELECT a FROM t WHERE a > 0 AND (b < 10 OR c = 'x') AND d IS NOT NULL")

        # Multiple asterisks
        extra.append("SELECT t1.*, t2.* FROM t1, t2")

        return extra
