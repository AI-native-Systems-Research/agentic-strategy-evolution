import os
import re

class Solution:
    def solve(self, resources_path: str) -> list[str]:
        # Read parser source to understand what features it supports
        parser_src = self._read(os.path.join(resources_path, "sql_engine", "parser.py"))
        tokenizer_src = self._read(os.path.join(resources_path, "sql_engine", "tokenizer.py"))

        # Start with the core statements that we know work
        stmts = list(self._base_stmts())

        # Add extra coverage based on parser analysis
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
        """Analyze parser source to find features not in base set."""
        extras = []

        # Look for specific keyword handling in the parser
        src = parser_src + tokenizer_src

        # ILIKE
        if 'ILIKE' in src:
            extras.append("SELECT a FROM t WHERE a ILIKE '%x%'")

        # RETURNING clause
        if 'RETURNING' in src:
            extras.append("INSERT INTO t (a) VALUES (1) RETURNING *")
            extras.append("UPDATE t SET a = 1 RETURNING *")
            extras.append("DELETE FROM t RETURNING *")

        # LATERAL
        if 'LATERAL' in src:
            extras.append("SELECT a FROM t1, LATERAL (SELECT * FROM t2 WHERE t2.id = t1.id) AS sub")

        # FILTER
        if 'FILTER' in src:
            extras.append("SELECT COUNT(*) FILTER (WHERE a > 0) FROM t")

        # CUBE / ROLLUP / GROUPING SETS
        if 'CUBE' in src:
            extras.append("SELECT a, SUM(b) FROM t GROUP BY CUBE (a)")
        if 'ROLLUP' in src:
            extras.append("SELECT a, SUM(b) FROM t GROUP BY ROLLUP (a)")
        if 'GROUPING' in src and 'SETS' in src:
            extras.append("SELECT a, SUM(b) FROM t GROUP BY GROUPING SETS ((a), ())")

        # DROP TABLE CASCADE / RESTRICT
        if 'CASCADE' in src:
            extras.append("DROP TABLE t CASCADE")
        if 'RESTRICT' in src:
            extras.append("DROP TABLE t RESTRICT")

        # START TRANSACTION
        if 'START' in src:
            extras.append("START TRANSACTION")

        # ROLLBACK TO (without SAVEPOINT)
        extras.append("ROLLBACK TO sp1")

        # TRUNCATE without TABLE
        extras.append("TRUNCATE t")

        # DROP VIEW
        if 'VIEW' in src:
            extras.append("DROP VIEW v")
            extras.append("DROP VIEW IF EXISTS v")

        # NULLS FIRST/LAST
        if 'NULLS' in src:
            extras.append("SELECT a FROM t ORDER BY a NULLS FIRST")
            extras.append("SELECT a FROM t ORDER BY a DESC NULLS LAST")

        # ON CONFLICT
        if 'CONFLICT' in src:
            extras.append("INSERT INTO t (a) VALUES (1) ON CONFLICT (a) DO NOTHING")
            extras.append("INSERT INTO t (a) VALUES (1) ON CONFLICT (a) DO UPDATE SET a = 2")

        # MERGE
        if 'MERGE' in src:
            extras.append("MERGE INTO t1 USING t2 ON t1.id = t2.id WHEN MATCHED THEN UPDATE SET a = t2.a WHEN NOT MATCHED THEN INSERT (a) VALUES (t2.a)")

        # WINDOW clause
        if 'WINDOW' in src:
            extras.append("SELECT SUM(b) OVER w FROM t WINDOW w AS (PARTITION BY c ORDER BY d)")

        # Additional window frames
        extras.append("SELECT SUM(b) OVER (ORDER BY a ROWS BETWEEN CURRENT ROW AND UNBOUNDED FOLLOWING) FROM t")

        # Additional functions
        if 'GREATEST' in src:
            extras.append("SELECT GREATEST(a, b, c) FROM t")
        if 'LEAST' in src:
            extras.append("SELECT LEAST(a, b, c) FROM t")
        if 'REPLACE' in src:
            extras.append("SELECT REPLACE(a, 'x', 'y') FROM t")
        if 'POSITION' in src:
            extras.append("SELECT POSITION('x' IN a) FROM t")

        # TRIM variants
        if 'LEADING' in src:
            extras.append("SELECT TRIM(LEADING ' ' FROM a) FROM t")
        if 'TRAILING' in src:
            extras.append("SELECT TRIM(TRAILING ' ' FROM a) FROM t")
        if 'BOTH' in src:
            extras.append("SELECT TRIM(BOTH ' ' FROM a) FROM t")

        # EXTRACT
        if 'EXTRACT' in src:
            extras.append("SELECT EXTRACT(YEAR FROM a) FROM t")
            extras.append("SELECT EXTRACT(MONTH FROM a) FROM t")
            extras.append("SELECT EXTRACT(DAY FROM a) FROM t")
            extras.append("SELECT EXTRACT(HOUR FROM a) FROM t")

        # CURRENT_TIME
        if 'CURRENT_TIME' in src:
            extras.append("SELECT CURRENT_TIME")

        # CAST to more types
        if 'CAST' in src:
            extras.append("SELECT CAST(a AS FLOAT) FROM t")
            extras.append("SELECT CAST(a AS BOOLEAN) FROM t")
            extras.append("SELECT CAST(a AS DATE) FROM t")

        # :: type cast
        if '::' in parser_src or 'TYPECAST' in src or 'typecast' in src:
            extras.append("SELECT a::TEXT FROM t")

        # Additional window functions
        if 'LAG' in src:
            extras.append("SELECT LAG(a, 1, 0) OVER (ORDER BY a) FROM t")
        if 'NTH_VALUE' in src:
            extras.append("SELECT NTH_VALUE(a, 2) OVER (ORDER BY a) FROM t")
        if 'PERCENT_RANK' in src:
            extras.append("SELECT PERCENT_RANK() OVER (ORDER BY a) FROM t")
        if 'CUME_DIST' in src:
            extras.append("SELECT CUME_DIST() OVER (ORDER BY a) FROM t")

        # INSERT DEFAULT VALUES
        if 'DEFAULT' in src:
            extras.append("INSERT INTO t DEFAULT VALUES")

        # ALTER TABLE extras
        if 'ALTER' in src and 'TYPE' in src:
            extras.append("ALTER TABLE t ALTER COLUMN a TYPE VARCHAR(100)")
        if 'CONSTRAINT' in src and 'CHECK' in src:
            extras.append("ALTER TABLE t ADD CONSTRAINT ck CHECK (a > 0)")
        if 'DROP' in src and 'CONSTRAINT' in src:
            extras.append("ALTER TABLE t DROP CONSTRAINT IF EXISTS pk")

        # Table constraints
        if 'UNIQUE' in src:
            extras.append("CREATE TABLE t (a INT, UNIQUE (a))")
        if 'FOREIGN' in src:
            extras.append("CREATE TABLE t (a INT, FOREIGN KEY (a) REFERENCES other(id))")

        # More data types
        if 'NUMERIC' in src:
            extras.append("CREATE TABLE t (a NUMERIC)")
        if 'BIGINT' in src:
            extras.append("CREATE TABLE t (a BIGINT)")
        if 'SMALLINT' in src:
            extras.append("CREATE TABLE t (a SMALLINT)")
        if 'SERIAL' in src:
            extras.append("CREATE TABLE t (a SERIAL PRIMARY KEY)")
        if 'DOUBLE' in src:
            extras.append("CREATE TABLE t (a DOUBLE PRECISION)")

        # TEMPORARY / TEMP tables
        if 'TEMPORARY' in src or 'TEMP' in src:
            extras.append("CREATE TEMPORARY TABLE tmp (a INT)")
            extras.append("CREATE TEMP TABLE tmp2 (a INT)")

        # Schema/Database operations
        if re.search(r'\bparse_create_schema\b|\bCREATE.*SCHEMA\b', src):
            extras.append("CREATE SCHEMA myschema")
            extras.append("DROP SCHEMA myschema")
        if re.search(r'\bparse_create_database\b|\bCREATE.*DATABASE\b', src):
            extras.append("CREATE DATABASE mydb")
            extras.append("DROP DATABASE mydb")

        # SEQUENCE
        if 'SEQUENCE' in src:
            extras.append("CREATE SEQUENCE myseq")
            extras.append("DROP SEQUENCE myseq")

        # GRANT extras
        if 'GRANT' in src:
            extras.append("GRANT INSERT, UPDATE ON t TO user1")

        # TABLESAMPLE
        if 'TABLESAMPLE' in src:
            extras.append("SELECT a FROM t TABLESAMPLE SYSTEM(10)")

        # FETCH
        if 'FETCH' in src and 'FIRST' in src:
            extras.append("SELECT a FROM t FETCH FIRST 5 ROWS ONLY")

        # SHOW
        if re.search(r'\bSHOW\b', src):
            extras.append("SHOW ALL")

        # VACUUM
        if 'VACUUM' in src:
            extras.append("VACUUM")

        # ANALYZE
        if re.search(r'\bparse_analyze\b', src):
            extras.append("ANALYZE t")

        # PREPARE / EXECUTE
        if 'PREPARE' in src:
            extras.append("PREPARE stmt AS SELECT 1")
        if re.search(r'\bparse_execute\b', src):
            extras.append("EXECUTE stmt")

        # DECLARE / CLOSE cursor
        if 'DECLARE' in src:
            extras.append("DECLARE cur CURSOR FOR SELECT a FROM t")
        if re.search(r'\bCLOSE\b', src):
            extras.append("CLOSE cur")

        # LOCK
        if re.search(r'\bLOCK\b', src):
            extras.append("LOCK TABLE t")

        # LISTEN / NOTIFY
        if 'LISTEN' in src:
            extras.append("LISTEN ch")
        if 'NOTIFY' in src:
            extras.append("NOTIFY ch")

        # COPY
        if re.search(r'\bCOPY\b', src):
            extras.append("COPY t FROM 'file.csv'")

        # COMMENT
        if re.search(r'\bCOMMENT\b', src):
            extras.append("COMMENT ON TABLE t IS 'desc'")

        # CREATE TABLE AS
        if 'AS' in src and 'SELECT' in src:
            extras.append("CREATE TABLE t2 AS SELECT a FROM t")

        # ON DELETE / ON UPDATE FK actions
        if 'ON DELETE' in parser_src or ('ON' in src and 'DELETE' in src and 'CASCADE' in src):
            extras.append("CREATE TABLE fk1 (a INT REFERENCES other(id) ON DELETE CASCADE)")
            extras.append("CREATE TABLE fk2 (a INT REFERENCES other(id) ON DELETE SET NULL)")
            extras.append("CREATE TABLE fk3 (a INT REFERENCES other(id) ON UPDATE CASCADE)")

        # Quoted identifiers
        extras.append('SELECT "col" FROM "tbl"')

        # Escaped string
        extras.append("SELECT 'it''s'")

        # Multiple FROM
        extras.append("SELECT a FROM t1, t2 WHERE t1.id = t2.id")

        # ADD without COLUMN
        extras.append("ALTER TABLE t ADD a INT")

        # Subquery with NOT IN
        extras.append("SELECT a FROM t WHERE a NOT IN (SELECT b FROM t2)")

        # JOIN with USING multiple cols
        extras.append("SELECT a FROM t1 JOIN t2 USING (id, name)")

        # Complex combined query
        extras.append("SELECT a, b FROM t1 LEFT JOIN t2 ON t1.id = t2.fk WHERE t1.active = TRUE GROUP BY a, b HAVING SUM(t2.amount) > 100 ORDER BY a DESC LIMIT 10 OFFSET 20")

        # OFFSET without LIMIT
        extras.append("SELECT a FROM t OFFSET 5")

        # LIKE with ESCAPE
        extras.append("SELECT a FROM t WHERE a LIKE 'x' ESCAPE '\\\\'")

        # Multiple column NOT NULL DEFAULT UNIQUE
        extras.append("CREATE TABLE t (a INTEGER NOT NULL DEFAULT 0 UNIQUE CHECK (a >= 0))")

        return extras

    def _base_stmts(self):
        return [
            "SELECT 1",
            "SELECT a FROM t",
            "SELECT a, b, c FROM t",
            "SELECT * FROM t",
            "SELECT DISTINCT a FROM t",
            "SELECT ALL a FROM t",
            "SELECT a AS x FROM t",
            "SELECT a AS x, b AS y FROM t AS z",
            "SELECT t.a FROM t",
            "SELECT t.* FROM t",
            "SELECT a FROM t WHERE a = 1",
            "SELECT a FROM t WHERE a != 1",
            "SELECT a FROM t WHERE a <> 1",
            "SELECT a FROM t WHERE a > 1",
            "SELECT a FROM t WHERE a < 1",
            "SELECT a FROM t WHERE a >= 1",
            "SELECT a FROM t WHERE a <= 1",
            "SELECT a FROM t WHERE a LIKE '%test%'",
            "SELECT a FROM t WHERE a NOT LIKE 'test%'",
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
            "SELECT a + b FROM t",
            "SELECT a - b FROM t",
            "SELECT a * b FROM t",
            "SELECT a / b FROM t",
            "SELECT a % b FROM t",
            "SELECT -a FROM t",
            "SELECT +a FROM t",
            "SELECT 'hello'",
            "SELECT 3.14",
            "SELECT -3.14",
            "SELECT 0",
            "SELECT TRUE, FALSE",
            "SELECT NULL",
            "SELECT a || b FROM t",
            "SELECT COUNT(*) FROM t",
            "SELECT COUNT(a) FROM t",
            "SELECT COUNT(DISTINCT a) FROM t",
            "SELECT SUM(a) FROM t",
            "SELECT AVG(a) FROM t",
            "SELECT MIN(a) FROM t",
            "SELECT MAX(a) FROM t",
            "SELECT a, COUNT(*) FROM t GROUP BY a",
            "SELECT a, COUNT(*) FROM t GROUP BY a HAVING COUNT(*) > 1",
            "SELECT a, b, SUM(c) FROM t GROUP BY a, b",
            "SELECT a FROM t ORDER BY a",
            "SELECT a FROM t ORDER BY a ASC",
            "SELECT a FROM t ORDER BY a DESC",
            "SELECT a FROM t ORDER BY a, b DESC",
            "SELECT a FROM t ORDER BY 1",
            "SELECT a FROM t LIMIT 10",
            "SELECT a FROM t LIMIT 10 OFFSET 5",
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
            "SELECT a FROM (SELECT b FROM t) AS sub",
            "SELECT a FROM t WHERE a IN (SELECT b FROM t2)",
            "SELECT a FROM t WHERE EXISTS (SELECT 1 FROM t2 WHERE t2.id = t.id)",
            "SELECT a FROM t WHERE NOT EXISTS (SELECT 1 FROM t2)",
            "SELECT (SELECT MAX(a) FROM t2) AS m FROM t",
            "SELECT a FROM t WHERE a > ANY (SELECT b FROM t2)",
            "SELECT a FROM t WHERE a > ALL (SELECT b FROM t2)",
            "SELECT a FROM t1 UNION SELECT b FROM t2",
            "SELECT a FROM t1 UNION ALL SELECT b FROM t2",
            "SELECT a FROM t1 INTERSECT SELECT b FROM t2",
            "SELECT a FROM t1 EXCEPT SELECT b FROM t2",
            "INSERT INTO t (a, b) VALUES (1, 2)",
            "INSERT INTO t VALUES (1, 2, 3)",
            "INSERT INTO t (a) VALUES (1), (2), (3)",
            "INSERT INTO t SELECT a FROM t2",
            "UPDATE t SET a = 1",
            "UPDATE t SET a = 1, b = 2",
            "UPDATE t SET a = 1 WHERE b = 2",
            "DELETE FROM t",
            "DELETE FROM t WHERE a = 1",
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
            "DROP TABLE t",
            "DROP TABLE IF EXISTS t",
            "CREATE INDEX idx ON t (a)",
            "CREATE UNIQUE INDEX idx ON t (a, b)",
            "CREATE INDEX IF NOT EXISTS idx ON t (a)",
            "DROP INDEX idx",
            "DROP INDEX IF EXISTS idx",
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
            "SELECT CASE WHEN a = 1 THEN 'one' WHEN a = 2 THEN 'two' ELSE 'other' END FROM t",
            "SELECT CASE a WHEN 1 THEN 'one' WHEN 2 THEN 'two' END FROM t",
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
            "WITH cte AS (SELECT a FROM t) SELECT * FROM cte",
            "WITH cte1 AS (SELECT a FROM t1), cte2 AS (SELECT b FROM t2) SELECT * FROM cte1 JOIN cte2 ON cte1.a = cte2.b",
            "WITH RECURSIVE cte AS (SELECT 1 AS n UNION ALL SELECT n + 1 FROM cte WHERE n < 10) SELECT * FROM cte",
            "SELECT DISTINCT ON (a) a, b FROM t",
            "SELECT DATE '2023-01-01'",
            "SELECT TIMESTAMP '2023-01-01 00:00:00'",
            "SELECT TIME '12:00:00'",
            "SELECT INTERVAL '1' DAY",
            "SELECT a FROM t1 WHERE a > (SELECT AVG(b) FROM t2) ORDER BY a LIMIT 5",
            "SELECT 1 + 2 * 3",
            "SELECT (1 + 2) * 3",
            "CREATE VIEW v AS SELECT a FROM t",
            "CREATE OR REPLACE VIEW v AS SELECT a FROM t",
            "TRUNCATE TABLE t",
            "BEGIN",
            "BEGIN TRANSACTION",
            "COMMIT",
            "ROLLBACK",
            "SAVEPOINT sp1",
            "RELEASE SAVEPOINT sp1",
            "ROLLBACK TO SAVEPOINT sp1",
            "EXPLAIN SELECT a FROM t",
            "EXPLAIN ANALYZE SELECT a FROM t",
            "SET search_path TO public",
            "GRANT SELECT ON t TO user1",
            "GRANT ALL ON t TO user1",
            "REVOKE SELECT ON t FROM user1",
            "SELECT a FROM t FOR UPDATE",
            "SELECT a FROM t FOR SHARE",
        ]
