import os
import re

class Solution:
    def solve(self, resources_path: str) -> list[str]:
        parser_src = self._read(os.path.join(resources_path, "sql_engine", "parser.py"))
        tokenizer_src = self._read(os.path.join(resources_path, "sql_engine", "tokenizer.py"))
        src = parser_src + tokenizer_src

        stmts = [
            # 1. SELECT with all column forms, aliases, qualified names
            "SELECT 1, a, b AS x, t.c, t.*, * FROM t AS z",

            # 2. SELECT DISTINCT
            "SELECT DISTINCT a FROM t",

            # 3. SELECT ALL
            "SELECT ALL a FROM t",

            # 4. WHERE with comparison ops - one per each to trigger each branch
            "SELECT a FROM t WHERE a = 1 AND b != 2 AND c <> 3 AND d > 4 AND e < 5 AND f >= 6 AND g <= 7",

            # 5. WHERE with LIKE, IN, BETWEEN, IS NULL, OR, NOT
            "SELECT a FROM t WHERE a LIKE '%x%' AND b NOT LIKE 'y%' AND c IN (1, 2, 3) AND d NOT IN (4, 5) AND e BETWEEN 1 AND 10 AND f NOT BETWEEN 20 AND 30 AND g IS NULL AND h IS NOT NULL AND NOT i = 0 AND (j = 1 OR k = 2)",

            # 6. Arithmetic, unary, string concat, parenthesized expr
            "SELECT a + b, a - b, a * b, a / b, a % b, -a, +a, a || b, (1 + 2) * 3 FROM t",

            # 7. All literals
            "SELECT 'hello', 3.14, -3.14, 0, TRUE, FALSE, NULL",

            # 8. All aggregates + GROUP BY + HAVING
            "SELECT a, COUNT(*), COUNT(a), COUNT(DISTINCT a), SUM(b), AVG(c), MIN(d), MAX(e) FROM t GROUP BY a, b HAVING COUNT(*) > 1",

            # 9. ORDER BY ASC, DESC + numeric
            "SELECT a FROM t ORDER BY a ASC, b DESC, 1",

            # 10. LIMIT + OFFSET
            "SELECT a FROM t LIMIT 10 OFFSET 5",

            # 11-16. JOINs (each triggers different branch)
            "SELECT a FROM t1 JOIN t2 ON t1.id = t2.id",
            "SELECT a FROM t1 LEFT OUTER JOIN t2 ON t1.id = t2.id",
            "SELECT a FROM t1 RIGHT OUTER JOIN t2 ON t1.id = t2.id",
            "SELECT a FROM t1 FULL OUTER JOIN t2 ON t1.id = t2.id",
            "SELECT a FROM t1 CROSS JOIN t2",
            "SELECT a FROM t1 NATURAL JOIN t2",
            "SELECT a FROM t1 JOIN t2 USING (id)",

            # 17. Subqueries in FROM, WHERE, SELECT
            "SELECT (SELECT MAX(a) FROM t2), a FROM (SELECT b AS a FROM t3) AS sub WHERE a IN (SELECT c FROM t4) AND EXISTS (SELECT 1 FROM t5) AND NOT EXISTS (SELECT 1 FROM t6)",

            # 18. ANY/ALL
            "SELECT a FROM t WHERE a > ANY (SELECT b FROM t2) AND a < ALL (SELECT c FROM t3)",

            # 19. Set operations
            "SELECT a FROM t1 UNION SELECT b FROM t2 UNION ALL SELECT c FROM t3",

            # 20. INTERSECT + EXCEPT
            "SELECT a FROM t1 INTERSECT SELECT b FROM t2",
            "SELECT a FROM t1 EXCEPT SELECT b FROM t2",

            # 21. INSERT variants
            "INSERT INTO t (a, b) VALUES (1, 2)",
            "INSERT INTO t VALUES (1, 2, 3)",
            "INSERT INTO t (a) VALUES (1), (2), (3)",
            "INSERT INTO t SELECT a FROM t2",

            # 22. UPDATE with SET + WHERE
            "UPDATE t SET a = 1, b = 2 WHERE c = 3",

            # 23. DELETE
            "DELETE FROM t WHERE a = 1",
            "DELETE FROM t",

            # 24. CREATE TABLE with many types and constraints
            "CREATE TABLE t (a INT PRIMARY KEY, b VARCHAR(255) NOT NULL, c FLOAT DEFAULT 0.0, d BOOLEAN, e DATE, f TIMESTAMP, g TEXT UNIQUE, h DECIMAL(10, 2), i INTEGER, j REAL, k CHAR(10))",

            # 25. CREATE TABLE with table constraints
            "CREATE TABLE t2 (a INT, b INT, PRIMARY KEY (a, b), UNIQUE (b), CHECK (a > 0))",

            # 26. CREATE TABLE IF NOT EXISTS + REFERENCES
            "CREATE TABLE IF NOT EXISTS t3 (a INT REFERENCES other(id), b INT CHECK (b > 0))",

            # 27. DROP TABLE
            "DROP TABLE t",
            "DROP TABLE IF EXISTS t",

            # 28. CREATE/DROP INDEX
            "CREATE INDEX idx ON t (a)",
            "CREATE UNIQUE INDEX idx2 ON t (a, b)",
            "CREATE INDEX IF NOT EXISTS idx3 ON t (a)",
            "DROP INDEX idx",
            "DROP INDEX IF EXISTS idx",

            # 29. ALTER TABLE - all variants
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

            # 30. CASE expressions - both forms
            "SELECT CASE WHEN a = 1 THEN 'one' ELSE 'other' END, CASE a WHEN 1 THEN 'x' WHEN 2 THEN 'y' END FROM t",

            # 31. Functions - consolidated
            "SELECT UPPER(a), LOWER(a), LENGTH(a), TRIM(a), ABS(a), ROUND(a, 2), CONCAT(a, b) FROM t",
            "SELECT SUBSTRING(a FROM 1 FOR 3), SUBSTR(a, 1, 3), COALESCE(a, b, c), NULLIF(a, b) FROM t",
            "SELECT CAST(a AS INT), CAST(b AS VARCHAR(100)) FROM t",
            "SELECT NOW(), CURRENT_TIMESTAMP, CURRENT_DATE",

            # 32. Window functions - consolidated
            "SELECT ROW_NUMBER() OVER (ORDER BY a), RANK() OVER (PARTITION BY b ORDER BY a), DENSE_RANK() OVER (ORDER BY a DESC) FROM t",
            "SELECT LAG(a, 1) OVER (ORDER BY a), LEAD(a, 1) OVER (ORDER BY a), NTILE(4) OVER (ORDER BY a) FROM t",
            "SELECT FIRST_VALUE(a) OVER (ORDER BY a), LAST_VALUE(a) OVER (ORDER BY a) FROM t",
            "SELECT SUM(b) OVER (ORDER BY a ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) FROM t",
            "SELECT SUM(b) OVER (ORDER BY a ROWS BETWEEN 1 PRECEDING AND 1 FOLLOWING) FROM t",
            "SELECT SUM(b) OVER (ORDER BY a RANGE BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) FROM t",
            "SELECT COUNT(*) OVER () FROM t",

            # 33. CTEs
            "WITH cte AS (SELECT a FROM t) SELECT * FROM cte",
            "WITH RECURSIVE cte AS (SELECT 1 AS n UNION ALL SELECT n + 1 FROM cte WHERE n < 10) SELECT * FROM cte",

            # 34. DISTINCT ON
            "SELECT DISTINCT ON (a) a, b FROM t",

            # 35. Typed literals
            "SELECT DATE '2023-01-01', TIMESTAMP '2023-01-01 00:00:00', TIME '12:00:00'",

            # 36. CREATE/DROP View
            "CREATE VIEW v AS SELECT a FROM t",
            "CREATE OR REPLACE VIEW v AS SELECT a FROM t",

            # 37. TRUNCATE
            "TRUNCATE TABLE t",

            # 38. Transactions
            "BEGIN",
            "COMMIT",
            "ROLLBACK",
            "SAVEPOINT sp1",
            "RELEASE SAVEPOINT sp1",
            "ROLLBACK TO SAVEPOINT sp1",

            # 39. EXPLAIN
            "EXPLAIN SELECT a FROM t",
            "EXPLAIN ANALYZE SELECT a FROM t",

            # 40. SET
            "SET search_path TO public",

            # 41. GRANT / REVOKE
            "GRANT SELECT ON t TO user1",
            "GRANT ALL ON t TO user1",
            "REVOKE SELECT ON t FROM user1",

            # 42. FOR UPDATE/SHARE
            "SELECT a FROM t FOR UPDATE",
            "SELECT a FROM t FOR SHARE",
        ]

        # Add dynamic extras based on parser features
        if 'ILIKE' in src:
            stmts.append("SELECT a FROM t WHERE a ILIKE '%x%'")
        if 'RETURNING' in src:
            stmts.append("INSERT INTO t (a) VALUES (1) RETURNING *")
        if 'LATERAL' in src:
            stmts.append("SELECT a FROM t1, LATERAL (SELECT * FROM t2 WHERE t2.id = t1.id) AS sub")
        if 'FILTER' in src:
            stmts.append("SELECT COUNT(*) FILTER (WHERE a > 0) FROM t")
        if 'CUBE' in src:
            stmts.append("SELECT a, SUM(b) FROM t GROUP BY CUBE (a)")
        if 'ROLLUP' in src:
            stmts.append("SELECT a, SUM(b) FROM t GROUP BY ROLLUP (a)")
        if 'NULLS' in src:
            stmts.append("SELECT a FROM t ORDER BY a NULLS FIRST")
        if 'CONFLICT' in src:
            stmts.append("INSERT INTO t (a) VALUES (1) ON CONFLICT (a) DO NOTHING")
        if 'MERGE' in src and 'MATCHED' in src:
            stmts.append("MERGE INTO t1 USING t2 ON t1.id = t2.id WHEN MATCHED THEN UPDATE SET a = t2.a WHEN NOT MATCHED THEN INSERT (a) VALUES (t2.a)")
        if 'WINDOW' in parser_src:
            stmts.append("SELECT SUM(b) OVER w FROM t WINDOW w AS (PARTITION BY c ORDER BY d)")
        if 'LEADING' in src:
            stmts.append("SELECT TRIM(LEADING ' ' FROM a) FROM t")
        if 'TRAILING' in src:
            stmts.append("SELECT TRIM(TRAILING ' ' FROM a) FROM t")
        if 'EXTRACT' in src:
            stmts.append("SELECT EXTRACT(YEAR FROM a) FROM t")
        if '::' in parser_src:
            stmts.append("SELECT a::INT FROM t")
        if 'TABLESAMPLE' in src:
            stmts.append("SELECT a FROM t TABLESAMPLE BERNOULLI(10)")
        if 'ARRAY' in src:
            stmts.append("SELECT ARRAY[1, 2, 3]")
        if 'SIMILAR' in parser_src:
            stmts.append("SELECT a FROM t WHERE a SIMILAR TO '%x%'")
        if 'CASCADE' in src:
            stmts.append("DROP TABLE t CASCADE")
        if 'SEQUENCE' in parser_src:
            stmts.append("CREATE SEQUENCE myseq")
        if 'SCHEMA' in parser_src:
            stmts.append("CREATE SCHEMA myschema")
        if 'DATABASE' in parser_src:
            stmts.append("CREATE DATABASE mydb")
        if 'TEMPORARY' in src or 'TEMP' in src:
            stmts.append("CREATE TEMPORARY TABLE tmp (a INT)")
        if 'SERIAL' in src:
            stmts.append("CREATE TABLE ts (a SERIAL PRIMARY KEY)")
        if 'NUMERIC' in src:
            stmts.append("CREATE TABLE tn (a NUMERIC, b BIGINT, c SMALLINT, d DOUBLE PRECISION)")
        if 'FOREIGN' in src and 'KEY' in src:
            stmts.append("CREATE TABLE tfk (a INT, FOREIGN KEY (a) REFERENCES other(id))")
        if 'GREATEST' in src:
            stmts.append("SELECT GREATEST(a, b) FROM t")
        if 'LEAST' in src:
            stmts.append("SELECT LEAST(a, b) FROM t")
        if 'POSITION' in parser_src:
            stmts.append("SELECT POSITION('x' IN a) FROM t")
        if 'NTH_VALUE' in src:
            stmts.append("SELECT NTH_VALUE(a, 2) OVER (ORDER BY a) FROM t")
        if 'PERCENT_RANK' in src:
            stmts.append("SELECT PERCENT_RANK() OVER (ORDER BY a) FROM t")
        if 'CUME_DIST' in src:
            stmts.append("SELECT CUME_DIST() OVER (ORDER BY a) FROM t")
        if 'LAG' in src:
            stmts.append("SELECT LAG(a, 1, 0) OVER (ORDER BY a) FROM t")
        if 'FETCH' in parser_src and 'FIRST' in parser_src:
            stmts.append("SELECT a FROM t FETCH FIRST 5 ROWS ONLY")
        if 'ON DELETE' in parser_src:
            stmts.append("CREATE TABLE fkd (a INT REFERENCES other(id) ON DELETE CASCADE)")
        if 'PREPARE' in parser_src:
            stmts.append("PREPARE stmt AS SELECT 1")
        if re.search(r'parse_execute', parser_src):
            stmts.append("EXECUTE stmt")
        if 'DECLARE' in parser_src:
            stmts.append("DECLARE cur CURSOR FOR SELECT a FROM t")
        if re.search(r'\bSHOW\b', parser_src):
            stmts.append("SHOW ALL")
        if 'VACUUM' in parser_src:
            stmts.append("VACUUM")
        if re.search(r'parse_analyze', parser_src):
            stmts.append("ANALYZE t")
        if 'LISTEN' in parser_src:
            stmts.append("LISTEN ch")
        if 'NOTIFY' in parser_src:
            stmts.append("NOTIFY ch")
        if re.search(r'\bCOPY\b', parser_src):
            stmts.append("COPY t FROM 'file.csv'")
        if re.search(r'\bCOMMENT\b', parser_src):
            stmts.append("COMMENT ON TABLE t IS 'desc'")
        if re.search(r'\bLOCK\b', parser_src):
            stmts.append("LOCK TABLE t")

        # Always-add (likely valid for most parsers)
        stmts.extend([
            "BEGIN TRANSACTION",
            "START TRANSACTION",
            "ROLLBACK TO sp1",
            "TRUNCATE t",
            "SELECT INTERVAL '1' DAY",
            "GRANT INSERT, UPDATE ON t TO user1",
            "INSERT INTO t DEFAULT VALUES",
            "DROP VIEW v",
            "DROP VIEW IF EXISTS v",
            "SELECT a FROM t1, t2 WHERE t1.id = t2.id",
            "SELECT CURRENT_TIME",
            "ALTER TABLE t ADD a INT",
            "ALTER TABLE t ALTER COLUMN a TYPE VARCHAR(100)",
            "ALTER TABLE t ADD CONSTRAINT ck CHECK (a > 0)",
            "ALTER TABLE t DROP CONSTRAINT IF EXISTS pk",
            'SELECT "col" FROM "tbl"',
            "SELECT 'it''s'",
        ])

        return stmts

    def _read(self, path):
        try:
            with open(path) as f:
                return f.read()
        except Exception:
            return ""
