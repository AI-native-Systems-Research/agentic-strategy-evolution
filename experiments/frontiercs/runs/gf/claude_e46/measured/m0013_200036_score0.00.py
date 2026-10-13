import os
import re

class Solution:
    def solve(self, resources_path: str) -> list[str]:
        parser_path = os.path.join(resources_path, "sql_engine", "parser.py")
        tokenizer_path = os.path.join(resources_path, "sql_engine", "tokenizer.py")
        ast_path = os.path.join(resources_path, "sql_engine", "ast_nodes.py")

        parser_src = self._read(parser_path)
        tokenizer_src = self._read(tokenizer_path)
        ast_src = self._read(ast_path)

        # Build a comprehensive but efficient set of SQL test cases
        # Analyze the parser to find exactly what features it supports
        stmts = self._base_stmts()

        # Add extra statements based on parser analysis
        extra = self._parser_guided(parser_src, tokenizer_src, ast_src)
        stmts.extend(extra)

        return stmts

    def _read(self, path):
        try:
            with open(path) as f:
                return f.read()
        except:
            return ""

    def _parser_guided(self, parser_src, tokenizer_src, ast_src):
        """Read parser source and generate SQL to cover specific branches."""
        extra = []

        if not parser_src:
            return extra

        # Find all parse methods to understand the structure
        methods = re.findall(r'def\s+(parse_\w+|_parse_\w+)', parser_src)

        # Find all keyword/token string comparisons
        all_keywords = set()
        # Pattern: .value == 'KEYWORD' or 'KEYWORD' == .value
        for m in re.finditer(r"\.value\s*==\s*'(\w+)'", parser_src):
            all_keywords.add(m.group(1))
        for m in re.finditer(r"'(\w+)'\s*==\s*\w+\.value", parser_src):
            all_keywords.add(m.group(1))
        # Pattern: _match('KEYWORD') or _expect('KEYWORD') or _check('KEYWORD')
        for m in re.finditer(r"(?:_match|_expect|_check|match|expect|check)\s*\(\s*'(\w+)'\s*\)", parser_src):
            all_keywords.add(m.group(1))
        # Pattern: in ('KW1', 'KW2', ...)
        for m in re.finditer(r"in\s*\(([^)]+)\)", parser_src):
            for kw in re.findall(r"'(\w+)'", m.group(1)):
                all_keywords.add(kw)
        # Pattern: in ['KW1', 'KW2', ...]
        for m in re.finditer(r"in\s*\[([^\]]+)\]", parser_src):
            for kw in re.findall(r"'(\w+)'", m.group(1)):
                all_keywords.add(kw)

        # Also extract from tokenizer
        for m in re.finditer(r"'(\w+)'", tokenizer_src):
            w = m.group(1)
            if w.isupper() and len(w) > 1:
                all_keywords.add(w)

        # Now check which keywords we need to generate SQL for
        # Map keywords to SQL statements that use them

        keyword_sql = {
            'ILIKE': "SELECT a FROM t WHERE a ILIKE '%x%'",
            'RETURNING': "INSERT INTO t (a) VALUES (1) RETURNING *",
            'LATERAL': "SELECT a FROM t1, LATERAL (SELECT * FROM t2 WHERE t2.id = t1.id) AS sub",
            'FILTER': "SELECT COUNT(*) FILTER (WHERE a > 0) FROM t",
            'CUBE': "SELECT a, SUM(b) FROM t GROUP BY CUBE (a)",
            'ROLLUP': "SELECT a, SUM(b) FROM t GROUP BY ROLLUP (a)",
            'TABLESAMPLE': "SELECT a FROM t TABLESAMPLE BERNOULLI(10)",
            'VACUUM': "VACUUM",
            'REINDEX': "REINDEX TABLE t",
            'CLUSTER': "CLUSTER t USING idx",
            'COPY': "COPY t FROM 'file.csv'",
            'SHOW': "SHOW ALL",
            'LISTEN': "LISTEN channel1",
            'NOTIFY': "NOTIFY channel1",
            'LOCK': "LOCK TABLE t",
            'PREPARE': "PREPARE stmt AS SELECT a FROM t WHERE a = $1",
            'EXECUTE': "EXECUTE stmt(1)",
            'DEALLOCATE': "DEALLOCATE stmt",
            'DECLARE': "DECLARE cur CURSOR FOR SELECT a FROM t",
            'CLOSE': "CLOSE cur",
            'CASCADE': "DROP TABLE t CASCADE",
            'RESTRICT': "DROP TABLE t RESTRICT",
            'TEMPORARY': "CREATE TEMPORARY TABLE tmp (a INT)",
            'TEMP': "CREATE TEMP TABLE tmp2 (a INT)",
            'SCHEMA': "CREATE SCHEMA myschema",
            'DATABASE': "CREATE DATABASE mydb",
            'SEQUENCE': "CREATE SEQUENCE myseq",
            'FETCH': "SELECT a FROM t FETCH FIRST 5 ROWS ONLY",
            'NULLS': "SELECT a FROM t ORDER BY a NULLS FIRST",
            'START': "START TRANSACTION",
            'REPLACE': "CREATE OR REPLACE VIEW v AS SELECT 1",
            'SIMILAR': "SELECT a FROM t WHERE a SIMILAR TO '%x%'",
            'ARRAY': "SELECT ARRAY[1, 2, 3]",
            'MERGE': "MERGE INTO t1 USING t2 ON t1.id = t2.id WHEN MATCHED THEN UPDATE SET a = t2.a WHEN NOT MATCHED THEN INSERT (a) VALUES (t2.a)",
            'CONFLICT': "INSERT INTO t (a) VALUES (1) ON CONFLICT (a) DO NOTHING",
            'EXCLUDED': "INSERT INTO t (a) VALUES (1) ON CONFLICT (a) DO UPDATE SET a = EXCLUDED.a",
            'MATCHED': "MERGE INTO t1 USING t2 ON t1.id = t2.id WHEN MATCHED THEN UPDATE SET a = t2.a WHEN NOT MATCHED THEN INSERT (a) VALUES (t2.a)",
            'SERIAL': "CREATE TABLE s (id SERIAL PRIMARY KEY)",
            'BIGINT': "CREATE TABLE b (a BIGINT)",
            'SMALLINT': "CREATE TABLE s (a SMALLINT)",
            'NUMERIC': "CREATE TABLE n (a NUMERIC)",
            'DOUBLE': "CREATE TABLE d (a DOUBLE PRECISION)",
            'INTERSECT': "SELECT 1 INTERSECT SELECT 1",
            'EXCEPT': "SELECT 1 EXCEPT SELECT 2",
            'WINDOW': "SELECT SUM(a) OVER w FROM t WINDOW w AS (ORDER BY a)",
            'CURRENT_TIME': "SELECT CURRENT_TIME",
            'CURRENT_DATE': "SELECT CURRENT_DATE",
            'CURRENT_TIMESTAMP': "SELECT CURRENT_TIMESTAMP",
            'INTERVAL': "SELECT INTERVAL '1 day'",
            'GROUPING': "SELECT a, SUM(b) FROM t GROUP BY GROUPING SETS ((a), ())",
            'MATERIALIZED': "CREATE MATERIALIZED VIEW mv AS SELECT a FROM t",
            'OVER': "SELECT COUNT(*) OVER () FROM t",
            'PARTITION': "SELECT RANK() OVER (PARTITION BY a ORDER BY b) FROM t",
            'ROWS': "SELECT SUM(a) OVER (ORDER BY b ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) FROM t",
            'RANGE': "SELECT SUM(a) OVER (ORDER BY b RANGE BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) FROM t",
            'UNBOUNDED': "SELECT SUM(a) OVER (ORDER BY b ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) FROM t",
            'PRECEDING': "SELECT SUM(a) OVER (ORDER BY b ROWS BETWEEN 1 PRECEDING AND CURRENT ROW) FROM t",
            'FOLLOWING': "SELECT SUM(a) OVER (ORDER BY b ROWS BETWEEN CURRENT ROW AND 1 FOLLOWING) FROM t",
            'PERCENT_RANK': "SELECT PERCENT_RANK() OVER (ORDER BY a) FROM t",
            'CUME_DIST': "SELECT CUME_DIST() OVER (ORDER BY a) FROM t",
            'NTH_VALUE': "SELECT NTH_VALUE(a, 2) OVER (ORDER BY a) FROM t",
            'NTILE': "SELECT NTILE(4) OVER (ORDER BY a) FROM t",
            'FIRST_VALUE': "SELECT FIRST_VALUE(a) OVER (ORDER BY a) FROM t",
            'LAST_VALUE': "SELECT LAST_VALUE(a) OVER (ORDER BY a) FROM t",
            'RECURSIVE': "WITH RECURSIVE cte AS (SELECT 1 AS n UNION ALL SELECT n + 1 FROM cte WHERE n < 10) SELECT * FROM cte",
            'TRIM': "SELECT TRIM(BOTH ' ' FROM a) FROM t",
            'LEADING': "SELECT TRIM(LEADING ' ' FROM a) FROM t",
            'TRAILING': "SELECT TRIM(TRAILING ' ' FROM a) FROM t",
            'BOTH': "SELECT TRIM(BOTH ' ' FROM a) FROM t",
            'SUBSTRING': "SELECT SUBSTRING(a FROM 1 FOR 3) FROM t",
            'POSITION': "SELECT POSITION('x' IN a) FROM t",
            'EXTRACT': "SELECT EXTRACT(YEAR FROM a) FROM t",
            'GREATEST': "SELECT GREATEST(a, b) FROM t",
            'LEAST': "SELECT LEAST(a, b) FROM t",
            'ESCAPE': "SELECT a FROM t WHERE a LIKE 'x' ESCAPE '\\\\'",
            'FOR': "SELECT a FROM t FOR UPDATE",
            'SHARE': "SELECT a FROM t FOR SHARE",
            'UPDATE': "UPDATE t SET a = 1",
        }

        seen_stmts = set(self._base_stmts())
        for kw, sql in keyword_sql.items():
            if kw in all_keywords and sql not in seen_stmts:
                extra.append(sql)
                seen_stmts.add(sql)

        # Check for ON DELETE/UPDATE actions
        if 'ON' in all_keywords and ('CASCADE' in all_keywords or 'ACTION' in all_keywords or 'RESTRICT' in all_keywords):
            extra.extend([
                "CREATE TABLE fk1 (a INT REFERENCES other(id) ON DELETE CASCADE)",
                "CREATE TABLE fk2 (a INT REFERENCES other(id) ON DELETE SET NULL)",
                "CREATE TABLE fk3 (a INT REFERENCES other(id) ON DELETE SET DEFAULT)",
                "CREATE TABLE fk4 (a INT REFERENCES other(id) ON DELETE RESTRICT)",
                "CREATE TABLE fk5 (a INT REFERENCES other(id) ON DELETE NO ACTION)",
                "CREATE TABLE fk6 (a INT REFERENCES other(id) ON UPDATE CASCADE)",
            ])

        # Check for specific AST node types that suggest features
        ast_classes = set(re.findall(r'class\s+(\w+)', ast_src))
        if 'LateralJoin' in ast_classes or 'Lateral' in ast_classes:
            if "LATERAL" not in all_keywords:
                extra.append("SELECT a FROM t1, LATERAL (SELECT * FROM t2 WHERE t2.id = t1.id) AS sub")

        # Check for specific parse_* methods that we might not be covering
        for method in methods:
            method_lower = method.lower()
            if 'parse_create_schema' in method_lower and 'SCHEMA' not in all_keywords:
                extra.append("CREATE SCHEMA s")
            if 'parse_create_database' in method_lower:
                extra.append("CREATE DATABASE d")
            if 'parse_create_sequence' in method_lower:
                extra.append("CREATE SEQUENCE seq")
            if 'parse_create_type' in method_lower:
                extra.append("CREATE TYPE mytype AS (a INT, b TEXT)")
            if 'parse_create_trigger' in method_lower:
                extra.append("CREATE TRIGGER trig BEFORE INSERT ON t FOR EACH ROW EXECUTE PROCEDURE func()")
            if 'parse_create_function' in method_lower:
                extra.append("CREATE FUNCTION func() RETURNS INT AS $$ SELECT 1 $$ LANGUAGE sql")
            if 'parse_do' in method_lower:
                extra.append("DO $$ BEGIN NULL; END $$")
            if 'parse_comment' in method_lower:
                extra.append("COMMENT ON TABLE t IS 'description'")
            if 'parse_create_table_as' in method_lower:
                extra.append("CREATE TABLE t AS SELECT a FROM other")

        # Look for error handling branches - often the parser has specific error recovery
        # These might not produce valid SQL but test error paths
        # However, invalid SQL doesn't help coverage per the problem rules

        # Check for RETURNING in UPDATE/DELETE
        if 'RETURNING' in all_keywords:
            extra.extend([
                "UPDATE t SET a = 1 RETURNING *",
                "DELETE FROM t RETURNING *",
                "INSERT INTO t (a) VALUES (1) RETURNING a, b",
            ])

        # Check for DISTINCT ON
        if 'DISTINCT' in all_keywords:
            extra.append("SELECT DISTINCT ON (a) a, b FROM t")

        # Check for additional CAST-like features
        if '::' in parser_src or 'TYPECAST' in all_keywords:
            extra.append("SELECT a::INT FROM t")
            extra.append("SELECT a::TEXT FROM t")

        # Check for quoted identifiers
        if '"' in tokenizer_src or 'QUOTED_IDENTIFIER' in tokenizer_src:
            extra.append('SELECT "col" FROM "tbl"')

        # Additional edge cases
        extra.extend([
            "SELECT a FROM t1, t2 WHERE t1.id = t2.id",
            "SELECT 'it''s'",
            "SELECT a FROM t WHERE a IN (SELECT b FROM t2 WHERE b > 0)",
            "SELECT CASE WHEN a IS NULL THEN 0 ELSE a END FROM t",
            "SELECT a FROM t ORDER BY a DESC NULLS LAST",
        ])

        return extra

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
            "SELECT a FROM t WHERE a LIKE 'test' ESCAPE '\\'",
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
            "SELECT a FROM t WHERE a SIMILAR TO '%pattern%'",
            "SELECT a FROM t FOR UPDATE",
            "SELECT a FROM t FOR SHARE",
            "SELECT a FROM t WHERE a::INT > 0",
            "SELECT a FROM t TABLESAMPLE BERNOULLI(10)",
            "SELECT ARRAY[1, 2, 3]",
            "SELECT a[1] FROM t",
        ]
