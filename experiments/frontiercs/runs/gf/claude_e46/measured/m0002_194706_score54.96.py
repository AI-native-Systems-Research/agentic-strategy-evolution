import os

class Solution:
    def solve(self, resources_path: str) -> list[str]:
        # Read the source files to understand what we need to cover
        parser_path = os.path.join(resources_path, "sql_engine", "parser.py")
        tokenizer_path = os.path.join(resources_path, "sql_engine", "tokenizer.py")
        ast_path = os.path.join(resources_path, "sql_engine", "ast_nodes.py")
        grammar_path = os.path.join(resources_path, "sql_grammar.txt")

        sources = {}
        for name, path in [("parser", parser_path), ("tokenizer", tokenizer_path),
                           ("ast", ast_path), ("grammar", grammar_path)]:
            try:
                with open(path, "r") as f:
                    sources[name] = f.read()
            except:
                sources[name] = ""

        # Generate comprehensive SQL based on parser analysis
        return self._generate_tests(sources)

    def _generate_tests(self, sources: dict) -> list[str]:
        parser_src = sources.get("parser", "")
        tokenizer_src = sources.get("tokenizer", "")
        grammar_src = sources.get("grammar", "")

        statements = []

        # ===== SELECT variants =====
        statements.extend([
            "SELECT 1",
            "SELECT *",
            "SELECT a FROM t",
            "SELECT a, b, c FROM t",
            "SELECT * FROM t",
            "SELECT DISTINCT a FROM t",
            "SELECT ALL a FROM t",

            # Aliases
            "SELECT a AS x FROM t",
            "SELECT a x FROM t",
            "SELECT t.a FROM t",
            "SELECT t.* FROM t",
            "SELECT a AS x, b AS y FROM t AS z",
        ])

        # ===== WHERE with all comparison operators =====
        statements.extend([
            "SELECT a FROM t WHERE a = 1",
            "SELECT a FROM t WHERE a != 1",
            "SELECT a FROM t WHERE a <> 1",
            "SELECT a FROM t WHERE a > 1",
            "SELECT a FROM t WHERE a < 1",
            "SELECT a FROM t WHERE a >= 1",
            "SELECT a FROM t WHERE a <= 1",
        ])

        # ===== LIKE / IN / BETWEEN / IS NULL =====
        statements.extend([
            "SELECT a FROM t WHERE a LIKE '%x%'",
            "SELECT a FROM t WHERE a NOT LIKE 'x%'",
            "SELECT a FROM t WHERE a ILIKE '%x%'",
            "SELECT a FROM t WHERE a IN (1, 2, 3)",
            "SELECT a FROM t WHERE a NOT IN (1, 2)",
            "SELECT a FROM t WHERE a BETWEEN 1 AND 10",
            "SELECT a FROM t WHERE a NOT BETWEEN 1 AND 10",
            "SELECT a FROM t WHERE a IS NULL",
            "SELECT a FROM t WHERE a IS NOT NULL",
        ])

        # ===== Logical operators =====
        statements.extend([
            "SELECT a FROM t WHERE a = 1 AND b = 2",
            "SELECT a FROM t WHERE a = 1 OR b = 2",
            "SELECT a FROM t WHERE NOT a = 1",
            "SELECT a FROM t WHERE (a = 1 OR b = 2) AND c = 3",
            "SELECT a FROM t WHERE NOT (a = 1 AND b = 2)",
        ])

        # ===== Arithmetic and unary =====
        statements.extend([
            "SELECT a + b FROM t",
            "SELECT a - b FROM t",
            "SELECT a * b FROM t",
            "SELECT a / b FROM t",
            "SELECT a % b FROM t",
            "SELECT -a FROM t",
            "SELECT +a FROM t",
            "SELECT 1 + 2 * 3",
            "SELECT (1 + 2) * 3",
        ])

        # ===== String concat =====
        statements.extend([
            "SELECT a || b FROM t",
            "SELECT 'hello' || ' ' || 'world'",
        ])

        # ===== Literals =====
        statements.extend([
            "SELECT 'hello'",
            "SELECT 3.14",
            "SELECT -3.14",
            "SELECT 0",
            "SELECT TRUE",
            "SELECT FALSE",
            "SELECT NULL",
        ])

        # ===== Aggregate functions =====
        statements.extend([
            "SELECT COUNT(*) FROM t",
            "SELECT COUNT(a) FROM t",
            "SELECT COUNT(DISTINCT a) FROM t",
            "SELECT SUM(a) FROM t",
            "SELECT AVG(a) FROM t",
            "SELECT MIN(a) FROM t",
            "SELECT MAX(a) FROM t",
        ])

        # ===== GROUP BY and HAVING =====
        statements.extend([
            "SELECT a, COUNT(*) FROM t GROUP BY a",
            "SELECT a, COUNT(*) FROM t GROUP BY a HAVING COUNT(*) > 1",
            "SELECT a, b, SUM(c) FROM t GROUP BY a, b",
            "SELECT a, COUNT(*) cnt FROM t GROUP BY a HAVING cnt > 0",
        ])

        # ===== ORDER BY =====
        statements.extend([
            "SELECT a FROM t ORDER BY a",
            "SELECT a FROM t ORDER BY a ASC",
            "SELECT a FROM t ORDER BY a DESC",
            "SELECT a FROM t ORDER BY a, b DESC",
            "SELECT a FROM t ORDER BY 1",
            "SELECT a FROM t ORDER BY a ASC NULLS FIRST",
            "SELECT a FROM t ORDER BY a DESC NULLS LAST",
        ])

        # ===== LIMIT / OFFSET =====
        statements.extend([
            "SELECT a FROM t LIMIT 10",
            "SELECT a FROM t LIMIT 10 OFFSET 5",
            "SELECT a FROM t OFFSET 5",
        ])

        # ===== JOINs =====
        statements.extend([
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
            "SELECT a FROM t1 JOIN t2 ON t1.id = t2.id JOIN t3 ON t2.id = t3.id",
        ])

        # ===== Subqueries =====
        statements.extend([
            "SELECT a FROM (SELECT b FROM t) AS sub",
            "SELECT a FROM t WHERE a IN (SELECT b FROM t2)",
            "SELECT a FROM t WHERE a NOT IN (SELECT b FROM t2)",
            "SELECT a FROM t WHERE EXISTS (SELECT 1 FROM t2 WHERE t2.id = t.id)",
            "SELECT a FROM t WHERE NOT EXISTS (SELECT 1 FROM t2)",
            "SELECT (SELECT MAX(a) FROM t2) AS m FROM t",
            "SELECT a FROM t WHERE a = (SELECT MAX(b) FROM t2)",
            "SELECT a FROM t WHERE a > ANY (SELECT b FROM t2)",
            "SELECT a FROM t WHERE a > ALL (SELECT b FROM t2)",
            "SELECT a FROM t WHERE a = SOME (SELECT b FROM t2)",
        ])

        # ===== UNION / INTERSECT / EXCEPT =====
        statements.extend([
            "SELECT a FROM t1 UNION SELECT b FROM t2",
            "SELECT a FROM t1 UNION ALL SELECT b FROM t2",
            "SELECT a FROM t1 INTERSECT SELECT b FROM t2",
            "SELECT a FROM t1 INTERSECT ALL SELECT b FROM t2",
            "SELECT a FROM t1 EXCEPT SELECT b FROM t2",
            "SELECT a FROM t1 EXCEPT ALL SELECT b FROM t2",
        ])

        # ===== INSERT =====
        statements.extend([
            "INSERT INTO t (a, b) VALUES (1, 2)",
            "INSERT INTO t VALUES (1, 2, 3)",
            "INSERT INTO t (a) VALUES (1), (2), (3)",
            "INSERT INTO t SELECT a FROM t2",
            "INSERT INTO t (a, b) VALUES (1, 'hello')",
            "INSERT INTO t DEFAULT VALUES",
        ])

        # ===== UPDATE =====
        statements.extend([
            "UPDATE t SET a = 1",
            "UPDATE t SET a = 1, b = 2",
            "UPDATE t SET a = 1 WHERE b = 2",
            "UPDATE t SET a = a + 1 WHERE b > 0",
        ])

        # ===== DELETE =====
        statements.extend([
            "DELETE FROM t",
            "DELETE FROM t WHERE a = 1",
            "DELETE FROM t WHERE a IN (1, 2, 3)",
        ])

        # ===== CREATE TABLE =====
        statements.extend([
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
            "CREATE TABLE t (a NUMERIC, b BIGINT, c SMALLINT, d DOUBLE PRECISION)",
            "CREATE TABLE t (a SERIAL PRIMARY KEY)",
            "CREATE TABLE t (a INT NOT NULL DEFAULT 0 UNIQUE)",
            "CREATE TABLE t (a INT, b INT, UNIQUE (a, b))",
            "CREATE TABLE t (a INT, b INT, FOREIGN KEY (a) REFERENCES other(id))",
            "CREATE TABLE t (a INT, b INT, CHECK (a > 0 AND b > 0))",
            "CREATE TABLE t (a TEXT, b BLOB, c CLOB)",
            "CREATE TEMPORARY TABLE t (a INT)",
            "CREATE TEMP TABLE t (a INT)",
        ])

        # ===== DROP TABLE =====
        statements.extend([
            "DROP TABLE t",
            "DROP TABLE IF EXISTS t",
            "DROP TABLE t CASCADE",
            "DROP TABLE t RESTRICT",
        ])

        # ===== CREATE INDEX =====
        statements.extend([
            "CREATE INDEX idx ON t (a)",
            "CREATE UNIQUE INDEX idx ON t (a, b)",
            "CREATE INDEX IF NOT EXISTS idx ON t (a)",
            "CREATE INDEX idx ON t (a ASC)",
            "CREATE INDEX idx ON t (a DESC)",
        ])

        # ===== DROP INDEX =====
        statements.extend([
            "DROP INDEX idx",
            "DROP INDEX IF EXISTS idx",
        ])

        # ===== ALTER TABLE =====
        statements.extend([
            "ALTER TABLE t ADD COLUMN a INT",
            "ALTER TABLE t ADD a INT",
            "ALTER TABLE t DROP COLUMN a",
            "ALTER TABLE t DROP a",
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
        ])

        # ===== CASE expressions =====
        statements.extend([
            "SELECT CASE WHEN a = 1 THEN 'one' WHEN a = 2 THEN 'two' ELSE 'other' END FROM t",
            "SELECT CASE a WHEN 1 THEN 'one' WHEN 2 THEN 'two' END FROM t",
            "SELECT CASE WHEN a > 0 THEN 'pos' ELSE 'neg' END FROM t",
            "SELECT CASE WHEN a IS NULL THEN 0 ELSE a END FROM t",
        ])

        # ===== Built-in functions =====
        statements.extend([
            "SELECT UPPER(a) FROM t",
            "SELECT LOWER(a) FROM t",
            "SELECT LENGTH(a) FROM t",
            "SELECT TRIM(a) FROM t",
            "SELECT TRIM(LEADING ' ' FROM a) FROM t",
            "SELECT TRIM(TRAILING ' ' FROM a) FROM t",
            "SELECT TRIM(BOTH ' ' FROM a) FROM t",
            "SELECT SUBSTRING(a FROM 1 FOR 3) FROM t",
            "SELECT SUBSTRING(a, 1, 3) FROM t",
            "SELECT SUBSTR(a, 1, 3) FROM t",
            "SELECT REPLACE(a, 'x', 'y') FROM t",
            "SELECT POSITION('x' IN a) FROM t",
            "SELECT COALESCE(a, b, c) FROM t",
            "SELECT NULLIF(a, b) FROM t",
            "SELECT GREATEST(a, b, c) FROM t",
            "SELECT LEAST(a, b, c) FROM t",
            "SELECT CAST(a AS INT) FROM t",
            "SELECT CAST(a AS VARCHAR(100)) FROM t",
            "SELECT CAST(a AS FLOAT) FROM t",
            "SELECT CAST(a AS BOOLEAN) FROM t",
            "SELECT CAST(a AS DATE) FROM t",
            "SELECT a::INT FROM t",
            "SELECT ABS(a) FROM t",
            "SELECT ROUND(a, 2) FROM t",
            "SELECT CEIL(a) FROM t",
            "SELECT FLOOR(a) FROM t",
            "SELECT POWER(a, 2) FROM t",
            "SELECT SQRT(a) FROM t",
            "SELECT MOD(a, b) FROM t",
            "SELECT CONCAT(a, b) FROM t",
            "SELECT CONCAT(a, b, c) FROM t",
            "SELECT LEFT(a, 3) FROM t",
            "SELECT RIGHT(a, 3) FROM t",
            "SELECT LPAD(a, 10, ' ') FROM t",
            "SELECT RPAD(a, 10, ' ') FROM t",
            "SELECT REVERSE(a) FROM t",
            "SELECT NOW()",
            "SELECT CURRENT_TIMESTAMP",
            "SELECT CURRENT_DATE",
            "SELECT CURRENT_TIME",
            "SELECT EXTRACT(YEAR FROM a) FROM t",
            "SELECT EXTRACT(MONTH FROM a) FROM t",
            "SELECT EXTRACT(DAY FROM a) FROM t",
            "SELECT EXTRACT(HOUR FROM a) FROM t",
            "SELECT EXTRACT(MINUTE FROM a) FROM t",
            "SELECT EXTRACT(SECOND FROM a) FROM t",
            "SELECT DATE_TRUNC('month', a) FROM t",
        ])

        # ===== Window functions =====
        statements.extend([
            "SELECT a, ROW_NUMBER() OVER (ORDER BY a) FROM t",
            "SELECT a, RANK() OVER (PARTITION BY b ORDER BY a) FROM t",
            "SELECT a, DENSE_RANK() OVER (ORDER BY a DESC) FROM t",
            "SELECT a, SUM(b) OVER (PARTITION BY c ORDER BY d) FROM t",
            "SELECT a, LAG(a, 1) OVER (ORDER BY a) FROM t",
            "SELECT a, LAG(a, 1, 0) OVER (ORDER BY a) FROM t",
            "SELECT a, LEAD(a, 1) OVER (ORDER BY a) FROM t",
            "SELECT a, FIRST_VALUE(a) OVER (ORDER BY a) FROM t",
            "SELECT a, LAST_VALUE(a) OVER (ORDER BY a) FROM t",
            "SELECT a, NTH_VALUE(a, 2) OVER (ORDER BY a) FROM t",
            "SELECT a, NTILE(4) OVER (ORDER BY a) FROM t",
            "SELECT a, PERCENT_RANK() OVER (ORDER BY a) FROM t",
            "SELECT a, CUME_DIST() OVER (ORDER BY a) FROM t",
            "SELECT a, SUM(b) OVER (ORDER BY a ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) FROM t",
            "SELECT a, SUM(b) OVER (ORDER BY a ROWS BETWEEN 1 PRECEDING AND 1 FOLLOWING) FROM t",
            "SELECT a, SUM(b) OVER (ORDER BY a RANGE BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) FROM t",
            "SELECT a, SUM(b) OVER (ORDER BY a ROWS BETWEEN CURRENT ROW AND UNBOUNDED FOLLOWING) FROM t",
            "SELECT a, COUNT(*) OVER () FROM t",
            "SELECT a, SUM(b) OVER w FROM t WINDOW w AS (PARTITION BY c ORDER BY d)",
        ])

        # ===== CTEs =====
        statements.extend([
            "WITH cte AS (SELECT a FROM t) SELECT * FROM cte",
            "WITH cte1 AS (SELECT a FROM t1), cte2 AS (SELECT b FROM t2) SELECT * FROM cte1 JOIN cte2 ON cte1.a = cte2.b",
            "WITH RECURSIVE cte AS (SELECT 1 AS n UNION ALL SELECT n + 1 FROM cte WHERE n < 10) SELECT * FROM cte",
        ])

        # ===== CREATE VIEW =====
        statements.extend([
            "CREATE VIEW v AS SELECT a FROM t",
            "CREATE OR REPLACE VIEW v AS SELECT a FROM t",
            "DROP VIEW v",
            "DROP VIEW IF EXISTS v",
        ])

        # ===== Transactions =====
        statements.extend([
            "BEGIN",
            "BEGIN TRANSACTION",
            "START TRANSACTION",
            "COMMIT",
            "ROLLBACK",
            "SAVEPOINT sp1",
            "RELEASE SAVEPOINT sp1",
            "ROLLBACK TO SAVEPOINT sp1",
            "ROLLBACK TO sp1",
        ])

        # ===== EXPLAIN =====
        statements.extend([
            "EXPLAIN SELECT a FROM t",
            "EXPLAIN ANALYZE SELECT a FROM t",
        ])

        # ===== TRUNCATE =====
        statements.extend([
            "TRUNCATE TABLE t",
            "TRUNCATE t",
        ])

        # ===== SET =====
        statements.extend([
            "SET search_path TO public",
            "SET a = 1",
        ])

        # ===== GRANT / REVOKE =====
        statements.extend([
            "GRANT SELECT ON t TO user1",
            "GRANT ALL ON t TO user1",
            "GRANT INSERT, UPDATE ON t TO user1",
            "GRANT SELECT ON t TO PUBLIC",
            "REVOKE SELECT ON t FROM user1",
            "REVOKE ALL ON t FROM user1",
        ])

        # ===== Typed literals =====
        statements.extend([
            "SELECT DATE '2023-01-01'",
            "SELECT TIME '12:00:00'",
            "SELECT TIMESTAMP '2023-01-01 00:00:00'",
            "SELECT INTERVAL '1 day'",
        ])

        # ===== Complex nested =====
        statements.extend([
            "SELECT a FROM t1 WHERE a > (SELECT AVG(b) FROM t2) ORDER BY a LIMIT 5",
            "SELECT a, b, c FROM t1 LEFT JOIN t2 ON t1.id = t2.fk WHERE t1.active = TRUE GROUP BY a, b, c HAVING SUM(t2.amount) > 100 ORDER BY a DESC LIMIT 10 OFFSET 20",
            "SELECT * FROM (SELECT a, ROW_NUMBER() OVER (PARTITION BY b ORDER BY c DESC) AS rn FROM t) sub WHERE rn = 1",
            "WITH ranked AS (SELECT a, RANK() OVER (ORDER BY b DESC) AS rnk FROM t) SELECT a FROM ranked WHERE rnk <= 10",
        ])

        # ===== MERGE / UPSERT =====
        statements.extend([
            "MERGE INTO t1 USING t2 ON t1.id = t2.id WHEN MATCHED THEN UPDATE SET a = t2.a WHEN NOT MATCHED THEN INSERT (id, a) VALUES (t2.id, t2.a)",
            "INSERT INTO t (a, b) VALUES (1, 2) ON CONFLICT (a) DO UPDATE SET b = 2",
            "INSERT INTO t (a, b) VALUES (1, 2) ON CONFLICT (a) DO NOTHING",
        ])

        # ===== Misc features =====
        statements.extend([
            "SELECT a FROM t FOR UPDATE",
            "SELECT a FROM t FOR SHARE",
            "SELECT a FROM t WHERE a SIMILAR TO '%pattern%'",
            "SELECT ARRAY[1, 2, 3]",
            "SELECT a[1] FROM t",
            "SELECT a FROM t FETCH FIRST 5 ROWS ONLY",
            "SELECT a FROM t FETCH NEXT 5 ROWS ONLY",
            "SELECT DISTINCT a, b FROM t",
        ])

        # ===== More expressions =====
        statements.extend([
            "SELECT a FROM t WHERE a = ANY(ARRAY[1, 2, 3])",
            "SELECT a FROM t WHERE a LIKE 'test' ESCAPE '\\'",
        ])

        return statements
