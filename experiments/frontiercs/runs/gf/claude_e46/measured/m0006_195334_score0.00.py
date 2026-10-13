import os
import re
import sys

class Solution:
    def solve(self, resources_path: str) -> list[str]:
        # Read parser source to understand exactly what code paths exist
        parser_src = self._read(os.path.join(resources_path, "sql_engine", "parser.py"))
        tokenizer_src = self._read(os.path.join(resources_path, "sql_engine", "tokenizer.py"))
        ast_src = self._read(os.path.join(resources_path, "sql_engine", "ast_nodes.py"))
        grammar_src = self._read(os.path.join(resources_path, "sql_grammar.txt"))

        # Try coverage-guided approach: import the parser and run it with coverage
        stmts = self._build_initial_corpus(parser_src, tokenizer_src, grammar_src)

        # Try to use coverage to filter and add statements
        try:
            stmts = self._coverage_guided(resources_path, stmts, parser_src, tokenizer_src, ast_src)
        except Exception:
            pass

        return stmts

    def _read(self, path):
        try:
            with open(path) as f:
                return f.read()
        except:
            return ""

    def _coverage_guided(self, resources_path, initial_stmts, parser_src, tokenizer_src, ast_src):
        """Use coverage module to find which statements actually add coverage."""
        import importlib
        import coverage

        # Add resources path parent to sys.path for imports
        engine_path = os.path.join(resources_path, "sql_engine")
        parent_path = resources_path

        if parent_path not in sys.path:
            sys.path.insert(0, parent_path)

        # Import the parser
        try:
            if 'sql_engine' in sys.modules:
                del sys.modules['sql_engine']
            if 'sql_engine.parser' in sys.modules:
                del sys.modules['sql_engine.parser']
            if 'sql_engine.tokenizer' in sys.modules:
                del sys.modules['sql_engine.tokenizer']
            if 'sql_engine.ast_nodes' in sys.modules:
                del sys.modules['sql_engine.ast_nodes']

            from sql_engine import parser as sql_parser
            parse_fn = None

            # Try to find the parse function
            if hasattr(sql_parser, 'parse_sql'):
                parse_fn = sql_parser.parse_sql
            elif hasattr(sql_parser, 'parse'):
                parse_fn = sql_parser.parse
            elif hasattr(sql_parser, 'Parser'):
                p = sql_parser.Parser()
                if hasattr(p, 'parse'):
                    parse_fn = p.parse
                elif hasattr(p, 'parse_sql'):
                    parse_fn = p.parse_sql

            if parse_fn is None:
                # Search for any callable that looks like a parser
                for name in dir(sql_parser):
                    obj = getattr(sql_parser, name)
                    if callable(obj) and 'parse' in name.lower():
                        parse_fn = obj
                        break

            if parse_fn is None:
                return initial_stmts

            # Get source files for coverage
            parser_file = os.path.join(engine_path, "parser.py")
            tokenizer_file = os.path.join(engine_path, "tokenizer.py")
            ast_file = os.path.join(engine_path, "ast_nodes.py")
            source_files = [f for f in [parser_file, tokenizer_file, ast_file] if os.path.exists(f)]

            # Run coverage-guided selection
            selected = []
            cov = coverage.Coverage(branch=True, source=[engine_path])
            cov.start()

            for stmt in initial_stmts:
                try:
                    parse_fn(stmt)
                except Exception:
                    pass

            cov.stop()
            baseline_data = cov.get_data()

            # Get baseline coverage stats
            baseline_lines = set()
            baseline_branches = set()
            for f in source_files:
                try:
                    lines = baseline_data.lines(f) or []
                    baseline_lines.update((f, l) for l in lines)
                except:
                    pass
                try:
                    arcs = baseline_data.arcs(f) or []
                    baseline_branches.update((f, a) for a in arcs)
                except:
                    pass

            # Now try to find which statements are redundant
            # First, run all of them and keep only those that add coverage
            selected = list(initial_stmts)  # start with all

            # Generate additional statements to try to cover remaining lines
            extra_stmts = self._generate_extra_stmts(parser_src, tokenizer_src)

            for stmt in extra_stmts:
                if stmt in selected:
                    continue
                # Quick test if this adds coverage
                cov2 = coverage.Coverage(branch=True, source=[engine_path])
                cov2.start()
                for s in selected:
                    try:
                        parse_fn(s)
                    except:
                        pass
                try:
                    parse_fn(stmt)
                except:
                    pass
                cov2.stop()
                data2 = cov2.get_data()

                new_lines = set()
                new_branches = set()
                for f in source_files:
                    try:
                        lines = data2.lines(f) or []
                        new_lines.update((f, l) for l in lines)
                    except:
                        pass
                    try:
                        arcs = data2.arcs(f) or []
                        new_branches.update((f, a) for a in arcs)
                    except:
                        pass

                if new_lines - baseline_lines or new_branches - baseline_branches:
                    selected.append(stmt)
                    baseline_lines = new_lines
                    baseline_branches = new_branches

            return selected

        except Exception:
            return initial_stmts

    def _generate_extra_stmts(self, parser_src, tokenizer_src):
        """Generate additional statements that might cover uncovered paths."""
        extras = [
            # Error paths that still parse partially
            "SELECT",
            "SELECT FROM",

            # Edge cases
            "SELECT a FROM t WHERE a ILIKE '%x%'",
            "SELECT DISTINCT ON (a) a, b FROM t ORDER BY a",

            # RETURNING
            "INSERT INTO t (a) VALUES (1) RETURNING *",
            "INSERT INTO t (a) VALUES (1) RETURNING a, b",
            "UPDATE t SET a = 1 RETURNING *",
            "DELETE FROM t WHERE a = 1 RETURNING *",

            # LATERAL
            "SELECT a FROM t1, LATERAL (SELECT * FROM t2 WHERE t2.id = t1.id) AS sub",

            # FILTER
            "SELECT COUNT(*) FILTER (WHERE a > 0) FROM t",

            # CUBE / ROLLUP
            "SELECT a, SUM(b) FROM t GROUP BY CUBE (a)",
            "SELECT a, SUM(b) FROM t GROUP BY ROLLUP (a)",
            "SELECT a, SUM(b) FROM t GROUP BY GROUPING SETS ((a), ())",

            # TABLESAMPLE
            "SELECT a FROM t TABLESAMPLE BERNOULLI(10)",
            "SELECT a FROM t TABLESAMPLE SYSTEM(10)",

            # ARRAY
            "SELECT ARRAY[1, 2, 3]",
            "SELECT a[1] FROM t",

            # FETCH
            "SELECT a FROM t FETCH FIRST 5 ROWS ONLY",
            "SELECT a FROM t FETCH NEXT 5 ROWS ONLY",

            # Complex CTE
            "WITH RECURSIVE cte(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM cte WHERE n < 5) SELECT * FROM cte",

            # Window frame variants
            "SELECT SUM(a) OVER (ORDER BY b ROWS UNBOUNDED PRECEDING) FROM t",
            "SELECT SUM(a) OVER (ORDER BY b RANGE CURRENT ROW) FROM t",

            # Cast operator
            "SELECT a::TEXT FROM t",
            "SELECT a::NUMERIC(10, 2) FROM t",

            # Nested CASE
            "SELECT CASE WHEN a > 0 THEN CASE WHEN b > 0 THEN 'both' ELSE 'a' END ELSE 'none' END FROM t",

            # Subquery in FROM with join
            "SELECT a FROM (SELECT x AS a FROM t1) s1 JOIN (SELECT y AS b FROM t2) s2 ON s1.a = s2.b",

            # Multiple set ops
            "SELECT a FROM t1 UNION SELECT b FROM t2 UNION ALL SELECT c FROM t3",

            # Deep nesting
            "SELECT a FROM t WHERE a IN (SELECT b FROM t2 WHERE b IN (SELECT c FROM t3))",

            # Multiple table FROM
            "SELECT a, b FROM t1, t2 WHERE t1.id = t2.id",

            # Aliased subquery in expression
            "SELECT (SELECT COUNT(*) FROM t2) + 1 FROM t",

            # BETWEEN with expressions
            "SELECT a FROM t WHERE a BETWEEN b AND c",

            # Complex WHERE
            "SELECT a FROM t WHERE a > 0 AND (b < 10 OR c = 'x') AND d IS NOT NULL",

            # Empty parens
            "SELECT a FROM t WHERE a IN ()",

            # Negative number literal
            "SELECT -1.5",
            "SELECT +1.5",

            # Multiple asterisks
            "SELECT t1.*, t2.* FROM t1, t2",

            # Schema qualified
            "SELECT a FROM schema1.t",

            # VACUUM / ANALYZE
            "VACUUM",
            "ANALYZE t",

            # SCHEMA operations
            "CREATE SCHEMA s",
            "DROP SCHEMA s",
            "DROP SCHEMA IF EXISTS s CASCADE",

            # DATABASE operations
            "CREATE DATABASE d",
            "DROP DATABASE d",

            # SEQUENCE
            "CREATE SEQUENCE seq",
            "DROP SEQUENCE seq",
            "CREATE SEQUENCE seq START WITH 1 INCREMENT BY 1",

            # PREPARE / EXECUTE
            "PREPARE stmt AS SELECT a FROM t WHERE a = $1",
            "EXECUTE stmt(1)",

            # DEALLOCATE
            "DEALLOCATE stmt",

            # DECLARE / FETCH cursor
            "DECLARE cur CURSOR FOR SELECT a FROM t",
            "FETCH NEXT FROM cur",
            "CLOSE cur",

            # LOCK
            "LOCK TABLE t",

            # SHOW
            "SHOW ALL",

            # LISTEN / NOTIFY
            "LISTEN channel1",
            "NOTIFY channel1",

            # COPY
            "COPY t FROM 'file.csv'",
            "COPY t TO 'file.csv'",

            # COMMENT
            "COMMENT ON TABLE t IS 'description'",

            # INSERT with RETURNING and ON CONFLICT
            "INSERT INTO t (a) VALUES (1) ON CONFLICT (a) DO UPDATE SET a = EXCLUDED.a RETURNING *",

            # UPDATE with FROM
            "UPDATE t SET a = t2.a FROM t2 WHERE t.id = t2.id",

            # DELETE with USING
            "DELETE FROM t USING t2 WHERE t.id = t2.id",

            # CREATE TABLE AS
            "CREATE TABLE t AS SELECT a FROM other",

            # CREATE INDEX with expressions
            "CREATE INDEX idx ON t (LOWER(a))",
            "CREATE INDEX idx ON t (a) WHERE b > 0",

            # String escape
            "SELECT 'it''s'",
            "SELECT E'hello\\nworld'",

            # Numeric edge cases
            "SELECT 1e10",
            "SELECT 1.5e-3",
            "SELECT .5",

            # Quoted identifiers
            'SELECT "column" FROM "table"',

            # Multiple constraints inline
            "CREATE TABLE t (a INT NOT NULL PRIMARY KEY REFERENCES other(id))",

            # ON DELETE/UPDATE actions
            "CREATE TABLE t (a INT REFERENCES other(id) ON DELETE CASCADE ON UPDATE SET NULL)",
            "CREATE TABLE t (a INT REFERENCES other(id) ON DELETE SET DEFAULT)",
            "CREATE TABLE t (a INT REFERENCES other(id) ON DELETE RESTRICT)",
            "CREATE TABLE t (a INT REFERENCES other(id) ON DELETE NO ACTION)",

            # UNIQUE with conflict
            "CREATE TABLE t (a INT, b INT, UNIQUE (a, b))",

            # CHECK with complex expr
            "CREATE TABLE t (a INT, CHECK (a > 0 AND a < 100))",

            # Multiple column definitions
            "CREATE TABLE t (id SERIAL PRIMARY KEY, name VARCHAR(100) NOT NULL, value DECIMAL(10, 2) DEFAULT 0.00, active BOOLEAN DEFAULT TRUE, created TIMESTAMP DEFAULT CURRENT_TIMESTAMP)",

            # ALTER with multiple actions
            "ALTER TABLE t ADD COLUMN b INT, ADD COLUMN c TEXT",

            # Complex GRANT
            "GRANT SELECT, INSERT, UPDATE, DELETE ON t TO role1",

            # WITH GRANT OPTION
            "GRANT SELECT ON t TO user1 WITH GRANT OPTION",

            # REVOKE with cascade
            "REVOKE ALL ON t FROM user1 CASCADE",
        ]

        return extras

    def _build_initial_corpus(self, parser_src, tokenizer_src, grammar_src):
        """Build initial set of SQL statements based on common patterns."""
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
            "CREATE TABLE t (a CHAR(10), b INTEGER, c BLOB, d CLOB)",
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

            # Built-in functions
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
        ]

        return stmts

