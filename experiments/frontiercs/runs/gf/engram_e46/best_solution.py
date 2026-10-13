# Approach: Dynamically analyze parser source code to generate targeted test cases
# Reads the grammar and parser at runtime, extracts code paths, generates SQL to cover them

import os
import re

class Solution:
    def solve(self, resources_path: str) -> list[str]:
        # Read all source files
        parser_src = self._read(os.path.join(resources_path, "sql_engine", "parser.py"))
        tokenizer_src = self._read(os.path.join(resources_path, "sql_engine", "tokenizer.py"))
        ast_src = self._read(os.path.join(resources_path, "sql_engine", "ast_nodes.py"))
        grammar_src = self._read(os.path.join(resources_path, "sql_grammar.txt"))
        
        all_src = parser_src + "\n" + tokenizer_src + "\n" + grammar_src
        
        # Extract all string literals that look like SQL keywords
        keywords = set()
        for m in re.finditer(r"['\"]([A-Z][A-Z_]{1,20})['\"]", all_src):
            keywords.add(m.group(1))
        
        # Extract all method names (parse_xxx)
        methods = set()
        for m in re.finditer(r'def\s+(\w+)', parser_src):
            methods.add(m.group(1))
        
        # Extract AST node class names
        ast_classes = set()
        for m in re.finditer(r'class\s+(\w+)', ast_src):
            ast_classes.add(m.group(1))
        
        # Build comprehensive test suite
        tests = []
        
        # Core SELECT variations
        tests.extend([
            "SELECT 1",
            "SELECT 1, 2, 3",
            "SELECT *",
            "SELECT * FROM t",
            "SELECT a, b FROM t",
            "SELECT DISTINCT a, b FROM t",
            "SELECT ALL a FROM t",
            "SELECT a AS x, b y FROM t u",
            "SELECT t.a, t.b FROM t",
            "SELECT t.* FROM t",
            "SELECT s.t.a FROM t",
        ])
        
        # WHERE with various operators
        tests.extend([
            "SELECT * FROM t WHERE a = 1",
            "SELECT * FROM t WHERE a != 1",
            "SELECT * FROM t WHERE a <> 1",
            "SELECT * FROM t WHERE a > 1",
            "SELECT * FROM t WHERE a < 1",
            "SELECT * FROM t WHERE a >= 1",
            "SELECT * FROM t WHERE a <= 1",
            "SELECT * FROM t WHERE a = 'hello'",
            "SELECT * FROM t WHERE a IS NULL",
            "SELECT * FROM t WHERE a IS NOT NULL",
            "SELECT * FROM t WHERE a IN (1, 2, 3)",
            "SELECT * FROM t WHERE a NOT IN (1, 2)",
            "SELECT * FROM t WHERE a IN (SELECT b FROM t2)",
            "SELECT * FROM t WHERE a BETWEEN 1 AND 10",
            "SELECT * FROM t WHERE a NOT BETWEEN 1 AND 10",
            "SELECT * FROM t WHERE a LIKE '%x%'",
            "SELECT * FROM t WHERE a NOT LIKE 'x%'",
            "SELECT * FROM t WHERE EXISTS (SELECT 1 FROM t2)",
            "SELECT * FROM t WHERE NOT EXISTS (SELECT 1 FROM t2)",
            "SELECT * FROM t WHERE a = 1 AND b = 2",
            "SELECT * FROM t WHERE a = 1 OR b = 2",
            "SELECT * FROM t WHERE NOT a = 1",
            "SELECT * FROM t WHERE (a = 1 OR b = 2) AND c = 3",
        ])
        
        # JOINS - comprehensive
        tests.extend([
            "SELECT * FROM t1 JOIN t2 ON t1.id = t2.id",
            "SELECT * FROM t1 INNER JOIN t2 ON t1.id = t2.id",
            "SELECT * FROM t1 LEFT JOIN t2 ON t1.id = t2.id",
            "SELECT * FROM t1 LEFT OUTER JOIN t2 ON t1.id = t2.id",
            "SELECT * FROM t1 RIGHT JOIN t2 ON t1.id = t2.id",
            "SELECT * FROM t1 RIGHT OUTER JOIN t2 ON t1.id = t2.id",
            "SELECT * FROM t1 FULL JOIN t2 ON t1.id = t2.id",
            "SELECT * FROM t1 FULL OUTER JOIN t2 ON t1.id = t2.id",
            "SELECT * FROM t1 CROSS JOIN t2",
            "SELECT * FROM t1 NATURAL JOIN t2",
            "SELECT * FROM t1 JOIN t2 USING (id)",
            "SELECT * FROM t1, t2",
            "SELECT * FROM t1 NATURAL LEFT JOIN t2",
        ])
        
        # GROUP BY / HAVING / ORDER BY
        tests.extend([
            "SELECT a, COUNT(*) FROM t GROUP BY a",
            "SELECT a, b, SUM(c) FROM t GROUP BY a, b",
            "SELECT a, COUNT(*) FROM t GROUP BY a HAVING COUNT(*) > 5",
            "SELECT * FROM t ORDER BY a",
            "SELECT * FROM t ORDER BY a ASC",
            "SELECT * FROM t ORDER BY a DESC",
            "SELECT * FROM t ORDER BY a, b DESC",
            "SELECT * FROM t ORDER BY 1",
        ])
        
        # NULLS FIRST/LAST if supported
        if 'NULLS' in keywords:
            tests.extend([
                "SELECT * FROM t ORDER BY a NULLS FIRST",
                "SELECT * FROM t ORDER BY a NULLS LAST",
                "SELECT * FROM t ORDER BY a ASC NULLS FIRST",
                "SELECT * FROM t ORDER BY a DESC NULLS LAST",
            ])
        
        # LIMIT / OFFSET
        tests.extend([
            "SELECT * FROM t LIMIT 10",
            "SELECT * FROM t LIMIT 10 OFFSET 20",
            "SELECT * FROM t ORDER BY a LIMIT 5 OFFSET 0",
        ])
        
        # Aggregate functions
        tests.extend([
            "SELECT COUNT(*) FROM t",
            "SELECT COUNT(a) FROM t",
            "SELECT COUNT(DISTINCT a) FROM t",
            "SELECT SUM(a), AVG(a), MIN(a), MAX(a) FROM t",
        ])
        
        # Arithmetic and expressions
        tests.extend([
            "SELECT a + b FROM t",
            "SELECT a - b FROM t",
            "SELECT a * b FROM t",
            "SELECT a / b FROM t",
            "SELECT a % b FROM t",
            "SELECT -a FROM t",
            "SELECT +a FROM t",
            "SELECT (a + b) * c FROM t",
            "SELECT a || b FROM t",
        ])
        
        # Functions
        tests.extend([
            "SELECT UPPER(a) FROM t",
            "SELECT LOWER(a) FROM t",
            "SELECT TRIM(a) FROM t",
            "SELECT SUBSTRING(a, 1, 3) FROM t",
            "SELECT LENGTH(a) FROM t",
            "SELECT COALESCE(a, b, 0) FROM t",
            "SELECT NULLIF(a, 0) FROM t",
            "SELECT ABS(a) FROM t",
            "SELECT ROUND(a, 2) FROM t",
        ])
        
        # CAST
        tests.extend([
            "SELECT CAST(a AS INTEGER) FROM t",
            "SELECT CAST(a AS VARCHAR) FROM t",
            "SELECT CAST(a AS TEXT) FROM t",
            "SELECT CAST(a AS FLOAT) FROM t",
            "SELECT CAST(a AS BOOLEAN) FROM t",
            "SELECT CAST(a AS DATE) FROM t",
            "SELECT CAST(a AS REAL) FROM t",
            "SELECT CAST(a AS NUMERIC) FROM t",
            "SELECT CAST(a AS DECIMAL(10, 2)) FROM t",
            "SELECT CAST(a AS VARCHAR(255)) FROM t",
        ])
        
        # CASE expressions
        tests.extend([
            "SELECT CASE WHEN a = 1 THEN 'one' WHEN a = 2 THEN 'two' ELSE 'other' END FROM t",
            "SELECT CASE a WHEN 1 THEN 'one' WHEN 2 THEN 'two' ELSE 'other' END FROM t",
            "SELECT CASE WHEN a > 0 THEN 'pos' END FROM t",
        ])
        
        # Subqueries
        tests.extend([
            "SELECT * FROM (SELECT a, b FROM t) sub",
            "SELECT a, (SELECT MAX(b) FROM t2) FROM t",
            "SELECT * FROM t WHERE a = (SELECT MAX(a) FROM t2)",
            "SELECT * FROM t WHERE a > ANY (SELECT b FROM t2)",
            "SELECT * FROM t WHERE a > ALL (SELECT b FROM t2)",
        ])
        
        # Set operations
        tests.extend([
            "SELECT a FROM t1 UNION SELECT a FROM t2",
            "SELECT a FROM t1 UNION ALL SELECT a FROM t2",
            "SELECT a FROM t1 INTERSECT SELECT a FROM t2",
            "SELECT a FROM t1 EXCEPT SELECT a FROM t2",
        ])
        
        # INSERT
        tests.extend([
            "INSERT INTO t (a, b) VALUES (1, 'hello')",
            "INSERT INTO t VALUES (1, 2, 3)",
            "INSERT INTO t (a) VALUES (1), (2), (3)",
            "INSERT INTO t SELECT * FROM t2",
            "INSERT INTO t (a, b) SELECT a, b FROM t2 WHERE c > 0",
        ])
        
        # UPDATE
        tests.extend([
            "UPDATE t SET a = 1",
            "UPDATE t SET a = 1, b = 'hello'",
            "UPDATE t SET a = 1 WHERE b = 2",
            "UPDATE t SET a = a + 1",
        ])
        
        # DELETE
        tests.extend([
            "DELETE FROM t",
            "DELETE FROM t WHERE a = 1",
        ])
        
        # CREATE TABLE
        tests.extend([
            "CREATE TABLE t (a INTEGER, b TEXT, c REAL)",
            "CREATE TABLE t (a INTEGER PRIMARY KEY, b VARCHAR NOT NULL, c FLOAT DEFAULT 0.0)",
            "CREATE TABLE IF NOT EXISTS t (a INTEGER)",
            "CREATE TABLE t (a INTEGER UNIQUE)",
            "CREATE TABLE t (a INTEGER REFERENCES other(id))",
            "CREATE TABLE t (a INTEGER CHECK (a > 0))",
            "CREATE TABLE t (a INTEGER, b TEXT, PRIMARY KEY (a))",
            "CREATE TABLE t (a INTEGER, FOREIGN KEY (a) REFERENCES other(id))",
            "CREATE TABLE t (a INTEGER, UNIQUE (a, b))",
            "CREATE TABLE t (a INTEGER, CHECK (a > 0 AND a < 100))",
            "CREATE TABLE t (a VARCHAR(255), b DECIMAL(10, 2))",
            "CREATE TABLE t (a INTEGER DEFAULT NULL, b TEXT DEFAULT 'hello')",
            "CREATE TABLE t AS SELECT * FROM other",
        ])
        
        # DROP TABLE
        tests.extend([
            "DROP TABLE t",
            "DROP TABLE IF EXISTS t",
        ])
        
        # ALTER TABLE
        if 'ALTER' in keywords:
            tests.extend([
                "ALTER TABLE t ADD COLUMN a INTEGER",
                "ALTER TABLE t DROP COLUMN a",
                "ALTER TABLE t RENAME TO t2",
                "ALTER TABLE t RENAME COLUMN a TO b",
                "ALTER TABLE t ALTER COLUMN a SET DEFAULT 0",
                "ALTER TABLE t ALTER COLUMN a DROP DEFAULT",
                "ALTER TABLE t ALTER COLUMN a SET NOT NULL",
                "ALTER TABLE t ALTER COLUMN a DROP NOT NULL",
                "ALTER TABLE t ALTER COLUMN a TYPE INTEGER",
            ])
        
        # INDEX
        tests.extend([
            "CREATE INDEX idx ON t (a)",
            "CREATE UNIQUE INDEX idx ON t (a, b)",
            "CREATE INDEX IF NOT EXISTS idx ON t (a)",
            "DROP INDEX idx",
            "DROP INDEX IF EXISTS idx",
        ])
        
        # VIEW
        tests.extend([
            "CREATE VIEW v AS SELECT * FROM t",
            "CREATE OR REPLACE VIEW v AS SELECT a FROM t WHERE a > 0",
            "DROP VIEW v",
            "DROP VIEW IF EXISTS v",
        ])
        
        # Window functions
        tests.extend([
            "SELECT ROW_NUMBER() OVER (ORDER BY a) FROM t",
            "SELECT RANK() OVER (PARTITION BY b ORDER BY a) FROM t",
            "SELECT DENSE_RANK() OVER (ORDER BY a DESC) FROM t",
            "SELECT SUM(a) OVER (PARTITION BY b ORDER BY c) FROM t",
            "SELECT SUM(a) OVER () FROM t",
            "SELECT AVG(a) OVER (ORDER BY b ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) FROM t",
            "SELECT SUM(a) OVER (ORDER BY b ROWS BETWEEN 1 PRECEDING AND 1 FOLLOWING) FROM t",
            "SELECT SUM(a) OVER (ORDER BY b RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) FROM t",
            "SELECT SUM(a) OVER (ORDER BY b ROWS UNBOUNDED PRECEDING) FROM t",
            "SELECT LAG(a, 1, 0) OVER (ORDER BY b) FROM t",
            "SELECT LEAD(a) OVER (ORDER BY b) FROM t",
            "SELECT FIRST_VALUE(a) OVER (ORDER BY b) FROM t",
            "SELECT LAST_VALUE(a) OVER (ORDER BY b) FROM t",
            "SELECT NTILE(4) OVER (ORDER BY a) FROM t",
            "SELECT SUM(a) OVER (ORDER BY b ROWS BETWEEN CURRENT ROW AND UNBOUNDED FOLLOWING) FROM t",
        ])
        
        # CTE
        tests.extend([
            "WITH cte AS (SELECT * FROM t) SELECT * FROM cte",
            "WITH c1 AS (SELECT a FROM t), c2 AS (SELECT b FROM t2) SELECT * FROM c1, c2",
        ])
        
        # RECURSIVE CTE
        if 'RECURSIVE' in keywords:
            tests.append("WITH RECURSIVE cte(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM cte WHERE n < 10) SELECT * FROM cte")
        
        # Transactions
        if 'BEGIN' in keywords or 'COMMIT' in keywords:
            tests.extend([
                "BEGIN",
                "BEGIN TRANSACTION",
                "COMMIT",
                "ROLLBACK",
            ])
        
        if 'SAVEPOINT' in keywords:
            tests.extend([
                "SAVEPOINT sp1",
                "RELEASE SAVEPOINT sp1",
                "ROLLBACK TO SAVEPOINT sp1",
            ])
        
        # EXPLAIN
        if 'EXPLAIN' in keywords:
            tests.append("EXPLAIN SELECT * FROM t")
        
        # TRUNCATE
        if 'TRUNCATE' in keywords:
            tests.append("TRUNCATE TABLE t")
        
        # Literals and edge cases
        tests.extend([
            "SELECT NULL",
            "SELECT TRUE",
            "SELECT FALSE",
            "SELECT 0",
            "SELECT 42",
            "SELECT 3.14",
            "SELECT 1.5e10",
            "SELECT 1.5E-3",
            "SELECT 'hello'",
            "SELECT 'it''s a test'",
            "SELECT ''",
            "SELECT a || 'suffix' FROM t",
        ])
        
        # EXTRACT
        if 'EXTRACT' in keywords:
            tests.extend([
                "SELECT EXTRACT(YEAR FROM d) FROM t",
                "SELECT EXTRACT(MONTH FROM d) FROM t",
                "SELECT EXTRACT(DAY FROM d) FROM t",
            ])
        
        # CURRENT_ 
        if 'CURRENT_TIMESTAMP' in keywords or 'CURRENT' in keywords:
            tests.extend([
                "SELECT CURRENT_TIMESTAMP",
                "SELECT CURRENT_DATE",
                "SELECT CURRENT_TIME",
            ])
        
        # ON CONFLICT
        if 'CONFLICT' in keywords:
            tests.extend([
                "INSERT INTO t (a) VALUES (1) ON CONFLICT DO NOTHING",
                "INSERT INTO t (a) VALUES (1) ON CONFLICT (a) DO UPDATE SET a = EXCLUDED.a",
            ])
        
        # RETURNING
        if 'RETURNING' in keywords:
            tests.extend([
                "INSERT INTO t (a) VALUES (1) RETURNING *",
                "INSERT INTO t (a) VALUES (1) RETURNING a, b",
                "UPDATE t SET a = 1 RETURNING *",
                "DELETE FROM t WHERE a = 1 RETURNING *",
            ])
        
        # LATERAL
        if 'LATERAL' in keywords:
            tests.append("SELECT * FROM t1, LATERAL (SELECT * FROM t2 WHERE t2.id = t1.id) sub")
        
        # FILTER
        if 'FILTER' in keywords:
            tests.append("SELECT COUNT(*) FILTER (WHERE a > 0) FROM t")
        
        # ILIKE
        if 'ILIKE' in keywords:
            tests.append("SELECT * FROM t WHERE a ILIKE '%pattern%'")
        
        # GROUPING SETS / ROLLUP / CUBE
        if 'ROLLUP' in keywords:
            tests.append("SELECT a, SUM(b) FROM t GROUP BY ROLLUP(a)")
        if 'CUBE' in keywords:
            tests.append("SELECT a, b, SUM(c) FROM t GROUP BY CUBE(a, b)")
        if 'GROUPING' in keywords:
            tests.append("SELECT a, b, SUM(c) FROM t GROUP BY GROUPING SETS ((a), (b), ())")
        
        # CASCADE / RESTRICT
        if 'CASCADE' in keywords:
            tests.append("DROP TABLE IF EXISTS t CASCADE")
        if 'RESTRICT' in keywords:
            tests.append("DROP TABLE t RESTRICT")
        
        # TEMPORARY
        if 'TEMPORARY' in keywords or 'TEMP' in keywords:
            tests.append("CREATE TEMPORARY TABLE tmp (a INTEGER)")
        
        # SHOW / SET
        if 'SHOW' in keywords:
            tests.append("SHOW ALL")
        if 'SET' in keywords and 'parse_set' in methods:
            tests.append("SET search_path TO public")
        
        # VACUUM / ANALYZE
        if 'VACUUM' in keywords:
            tests.append("VACUUM")
        if 'ANALYZE' in keywords:
            tests.append("ANALYZE t")
        
        # WINDOW clause
        if 'WINDOW' in keywords:
            tests.append("SELECT a, SUM(b) OVER w FROM t WINDOW w AS (ORDER BY a)")
        
        # Complex combined
        tests.append("SELECT DISTINCT a, SUM(b) AS total FROM t1 JOIN t2 ON t1.id = t2.id WHERE t1.c > 0 GROUP BY a HAVING SUM(b) > 100 ORDER BY total DESC LIMIT 10 OFFSET 5")
        
        # Multiple join chain
        tests.append("SELECT * FROM t1 JOIN t2 ON t1.a = t2.a LEFT JOIN t3 ON t2.b = t3.b")
        
        # Nested subqueries
        tests.append("SELECT * FROM (SELECT * FROM (SELECT a FROM t) s1) s2")
        
        # TABLESAMPLE
        if 'TABLESAMPLE' in keywords:
            tests.append("SELECT * FROM t TABLESAMPLE BERNOULLI(10)")
        
        # ARRAY
        if 'ARRAY' in keywords:
            tests.extend(["SELECT ARRAY[1, 2, 3]", "SELECT a[1] FROM t"])
        
        # Schema qualified
        tests.append("SELECT * FROM schema1.table1")
        
        # GLOB/REGEXP
        if 'GLOB' in keywords:
            tests.append("SELECT * FROM t WHERE a GLOB '*test*'")
        if 'REGEXP' in keywords:
            tests.append("SELECT * FROM t WHERE a REGEXP 'pattern'")
        if 'SIMILAR' in keywords:
            tests.append("SELECT * FROM t WHERE a SIMILAR TO '%test%'")
        
        # Boolean operators
        if 'ISNULL' in keywords:
            tests.append("SELECT * FROM t WHERE a ISNULL")
        if 'NOTNULL' in keywords:
            tests.append("SELECT * FROM t WHERE a NOTNULL")
            
        # Parameterized types
        tests.append("SELECT CAST(a AS VARCHAR(100)) FROM t")
        tests.append("SELECT CAST(a AS DECIMAL(10,2)) FROM t")
        tests.append("SELECT CAST(a AS NUMERIC(5)) FROM t")
        
        return tests
    
    def _read(self, path):
        try:
            with open(path, 'r') as f:
                return f.read()
        except:
            return ""

