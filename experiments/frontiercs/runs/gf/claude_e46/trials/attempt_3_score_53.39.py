import os
import re
import ast as pyast
import sys

class Solution:
    def solve(self, resources_path: str) -> list[str]:
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

        return self._generate_tests(sources)

    def _analyze_parser(self, parser_src):
        """Extract useful info from parser source to guide test generation."""
        info = {
            "methods": re.findall(r'def\s+(\w+)', parser_src),
            "string_literals": re.findall(r"'([A-Z_]+)'", parser_src),
            "keywords_checked": set(),
            "token_types": set(),
        }

        # Find all string comparisons (keywords the parser checks for)
        for m in re.finditer(r"==\s*['\"](\w+)['\"]|['\"](\w+)['\"]\s*==", parser_src):
            kw = m.group(1) or m.group(2)
            info["keywords_checked"].add(kw)

        # Find token type checks
        for m in re.finditer(r"TokenType\.(\w+)", parser_src):
            info["token_types"].add(m.group(1))

        # Find keywords in if/elif conditions
        for m in re.finditer(r"(?:if|elif)\s+.*?['\"](\w+)['\"]", parser_src):
            info["keywords_checked"].add(m.group(1))

        return info

    def _analyze_tokenizer(self, tokenizer_src):
        """Extract token types and keywords from tokenizer."""
        info = {
            "keywords": set(),
            "token_types": set(),
            "operators": set(),
        }

        # Find keyword mappings
        for m in re.finditer(r"['\"](\w+)['\"]", tokenizer_src):
            word = m.group(1)
            if word.isupper() and len(word) > 1:
                info["keywords"].add(word)

        # Find operator patterns
        for m in re.finditer(r"['\"]([<>=!]+)['\"]", tokenizer_src):
            info["operators"].add(m.group(1))

        return info

    def _analyze_grammar(self, grammar_src):
        """Extract rules from BNF grammar."""
        rules = {}
        current_rule = None
        for line in grammar_src.split('\n'):
            line = line.strip()
            m = re.match(r'<(\w+)>\s*::=\s*(.*)', line)
            if m:
                current_rule = m.group(1)
                rules[current_rule] = [m.group(2).strip()]
            elif line.startswith('|') and current_rule:
                rules[current_rule].append(line[1:].strip())
            elif current_rule and line:
                rules.setdefault(current_rule, []).append(line)
        return rules

    def _generate_tests(self, sources: dict) -> list[str]:
        parser_info = self._analyze_parser(sources.get("parser", ""))
        tokenizer_info = self._analyze_tokenizer(sources.get("tokenizer", ""))
        grammar_rules = self._analyze_grammar(sources.get("grammar", ""))

        statements = []

        # ===== Core SELECT =====
        statements.extend([
            "SELECT 1",
            "SELECT a, b FROM t",
            "SELECT * FROM t",
            "SELECT DISTINCT a FROM t",
            "SELECT ALL a FROM t",
            "SELECT a AS x FROM t AS y",
            "SELECT t.a, t.b FROM t",
            "SELECT t.* FROM t",
            "SELECT a x FROM t",
        ])

        # ===== WHERE =====
        statements.extend([
            "SELECT a FROM t WHERE a = 1",
            "SELECT a FROM t WHERE a != 1",
            "SELECT a FROM t WHERE a <> 1",
            "SELECT a FROM t WHERE a > 1",
            "SELECT a FROM t WHERE a < 1",
            "SELECT a FROM t WHERE a >= 1",
            "SELECT a FROM t WHERE a <= 1",
            "SELECT a FROM t WHERE a LIKE '%x%'",
            "SELECT a FROM t WHERE a NOT LIKE 'x%'",
            "SELECT a FROM t WHERE a ILIKE '%x%'",
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
        ])

        # ===== Arithmetic =====
        statements.extend([
            "SELECT a + b, a - b, a * b, a / b, a % b FROM t",
            "SELECT -a, +a FROM t",
            "SELECT (1 + 2) * 3",
            "SELECT a || b FROM t",
        ])

        # ===== Literals =====
        statements.extend([
            "SELECT 'hello', 3.14, -42, 0, TRUE, FALSE, NULL",
        ])

        # ===== Aggregates, GROUP BY, HAVING =====
        statements.extend([
            "SELECT COUNT(*), COUNT(a), COUNT(DISTINCT a), SUM(a), AVG(a), MIN(a), MAX(a) FROM t GROUP BY a HAVING COUNT(*) > 1",
        ])

        # ===== ORDER BY =====
        statements.extend([
            "SELECT a FROM t ORDER BY a ASC, b DESC",
            "SELECT a FROM t ORDER BY a NULLS FIRST",
            "SELECT a FROM t ORDER BY a DESC NULLS LAST",
        ])

        # ===== LIMIT / OFFSET =====
        statements.extend([
            "SELECT a FROM t LIMIT 10 OFFSET 5",
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
        ])

        # ===== Subqueries =====
        statements.extend([
            "SELECT a FROM (SELECT b FROM t) AS sub",
            "SELECT a FROM t WHERE a IN (SELECT b FROM t2)",
            "SELECT a FROM t WHERE EXISTS (SELECT 1 FROM t2 WHERE t2.id = t.id)",
            "SELECT a FROM t WHERE NOT EXISTS (SELECT 1 FROM t2)",
            "SELECT (SELECT MAX(a) FROM t2) AS m FROM t",
            "SELECT a FROM t WHERE a > ANY (SELECT b FROM t2)",
            "SELECT a FROM t WHERE a > ALL (SELECT b FROM t2)",
        ])

        # ===== Set operations =====
        statements.extend([
            "SELECT a FROM t1 UNION SELECT b FROM t2",
            "SELECT a FROM t1 UNION ALL SELECT b FROM t2",
            "SELECT a FROM t1 INTERSECT SELECT b FROM t2",
            "SELECT a FROM t1 EXCEPT SELECT b FROM t2",
        ])

        # ===== INSERT =====
        statements.extend([
            "INSERT INTO t (a, b) VALUES (1, 2)",
            "INSERT INTO t VALUES (1, 2, 3)",
            "INSERT INTO t (a) VALUES (1), (2), (3)",
            "INSERT INTO t SELECT a FROM t2",
            "INSERT INTO t DEFAULT VALUES",
        ])

        # ===== UPDATE =====
        statements.extend([
            "UPDATE t SET a = 1, b = 2 WHERE c = 3",
        ])

        # ===== DELETE =====
        statements.extend([
            "DELETE FROM t WHERE a = 1",
            "DELETE FROM t",
        ])

        # ===== CREATE TABLE =====
        statements.extend([
            "CREATE TABLE t (a INT PRIMARY KEY, b VARCHAR(255) NOT NULL, c FLOAT DEFAULT 0.0, d BOOLEAN, e DATE, f TIMESTAMP, g TEXT UNIQUE)",
            "CREATE TABLE IF NOT EXISTS t (a INT)",
            "CREATE TABLE t (a INT, b INT, PRIMARY KEY (a, b))",
            "CREATE TABLE t (a INT REFERENCES other(id))",
            "CREATE TABLE t (a INT CHECK (a > 0))",
            "CREATE TABLE t (a DECIMAL(10, 2), b NUMERIC, c BIGINT, d SMALLINT, e REAL, f DOUBLE PRECISION)",
            "CREATE TABLE t (a INT, UNIQUE (a))",
            "CREATE TABLE t (a INT, b INT, FOREIGN KEY (a) REFERENCES other(id))",
            "CREATE TABLE t (a SERIAL PRIMARY KEY)",
            "CREATE TABLE t (a CHAR(10), b BLOB, c CLOB)",
            "CREATE TABLE t (a INTEGER NOT NULL DEFAULT 0 UNIQUE CHECK (a >= 0))",
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

        # ===== CREATE/DROP INDEX =====
        statements.extend([
            "CREATE INDEX idx ON t (a)",
            "CREATE UNIQUE INDEX idx ON t (a, b)",
            "CREATE INDEX IF NOT EXISTS idx ON t (a)",
            "DROP INDEX idx",
            "DROP INDEX IF EXISTS idx",
        ])

        # ===== ALTER TABLE =====
        statements.extend([
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
        ])

        # ===== CASE =====
        statements.extend([
            "SELECT CASE WHEN a = 1 THEN 'one' WHEN a = 2 THEN 'two' ELSE 'other' END FROM t",
            "SELECT CASE a WHEN 1 THEN 'one' WHEN 2 THEN 'two' END FROM t",
        ])

        # ===== Functions =====
        statements.extend([
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
            "SELECT CAST(a AS FLOAT) FROM t",
            "SELECT CAST(a AS BOOLEAN) FROM t",
            "SELECT CAST(a AS DATE) FROM t",
            "SELECT a::INT FROM t",
            "SELECT CEIL(a), FLOOR(a), POWER(a, 2), SQRT(a), MOD(a, b) FROM t",
            "SELECT CONCAT(a, b, c) FROM t",
            "SELECT LEFT(a, 3), RIGHT(a, 3) FROM t",
            "SELECT LPAD(a, 10, ' '), RPAD(a, 10, ' ') FROM t",
            "SELECT NOW()",
            "SELECT CURRENT_TIMESTAMP",
            "SELECT CURRENT_DATE",
            "SELECT CURRENT_TIME",
            "SELECT EXTRACT(YEAR FROM a) FROM t",
            "SELECT EXTRACT(MONTH FROM a) FROM t",
            "SELECT EXTRACT(DAY FROM a) FROM t",
            "SELECT EXTRACT(HOUR FROM a) FROM t",
        ])

        # ===== Window functions =====
        statements.extend([
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
        ])

        # ===== CTEs =====
        statements.extend([
            "WITH cte AS (SELECT a FROM t) SELECT * FROM cte",
            "WITH cte1 AS (SELECT a FROM t1), cte2 AS (SELECT b FROM t2) SELECT * FROM cte1 JOIN cte2 ON cte1.a = cte2.b",
            "WITH RECURSIVE cte AS (SELECT 1 AS n UNION ALL SELECT n + 1 FROM cte WHERE n < 10) SELECT * FROM cte",
        ])

        # ===== CREATE/DROP VIEW =====
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

        # ===== GRANT / REVOKE =====
        statements.extend([
            "GRANT SELECT ON t TO user1",
            "GRANT ALL ON t TO user1",
            "GRANT INSERT, UPDATE ON t TO user1",
            "REVOKE SELECT ON t FROM user1",
        ])

        # ===== MERGE / UPSERT =====
        statements.extend([
            "MERGE INTO t1 USING t2 ON t1.id = t2.id WHEN MATCHED THEN UPDATE SET a = t2.a WHEN NOT MATCHED THEN INSERT (id, a) VALUES (t2.id, t2.a)",
            "INSERT INTO t (a, b) VALUES (1, 2) ON CONFLICT (a) DO UPDATE SET b = 2",
            "INSERT INTO t (a, b) VALUES (1, 2) ON CONFLICT (a) DO NOTHING",
        ])

        # ===== Typed literals =====
        statements.extend([
            "SELECT DATE '2023-01-01'",
            "SELECT TIME '12:00:00'",
            "SELECT TIMESTAMP '2023-01-01 00:00:00'",
            "SELECT INTERVAL '1 day'",
        ])

        # ===== Misc =====
        statements.extend([
            "SELECT a FROM t FOR UPDATE",
            "SELECT a FROM t FOR SHARE",
            "SELECT ARRAY[1, 2, 3]",
            "SELECT a[1] FROM t",
            "SELECT a FROM t FETCH FIRST 5 ROWS ONLY",
        ])

        # ===== Dynamic: if parser has specific methods, generate targeted SQL =====
        methods = set(parser_info.get("methods", []))
        kw = parser_info.get("keywords_checked", set()) | tokenizer_info.get("keywords", set())

        # Check for specific features in the parser/tokenizer
        if "LATERAL" in kw or "parse_lateral" in " ".join(methods):
            statements.append("SELECT a FROM t1, LATERAL (SELECT * FROM t2 WHERE t2.id = t1.id) AS sub")

        if "HAVING" in kw:
            pass  # already covered

        if "RETURNING" in kw:
            statements.extend([
                "INSERT INTO t (a) VALUES (1) RETURNING *",
                "INSERT INTO t (a) VALUES (1) RETURNING a",
                "UPDATE t SET a = 1 RETURNING *",
                "DELETE FROM t WHERE a = 1 RETURNING *",
            ])

        if "DISTINCT" in kw:
            statements.append("SELECT DISTINCT ON (a) a, b FROM t")

        if "FILTER" in kw:
            statements.append("SELECT COUNT(*) FILTER (WHERE a > 0) FROM t")

        if "GROUPING" in kw:
            statements.append("SELECT GROUPING(a) FROM t GROUP BY a")

        if "CUBE" in kw or "ROLLUP" in kw:
            statements.extend([
                "SELECT a, b, SUM(c) FROM t GROUP BY CUBE (a, b)",
                "SELECT a, b, SUM(c) FROM t GROUP BY ROLLUP (a, b)",
                "SELECT a, b, SUM(c) FROM t GROUP BY GROUPING SETS ((a), (b), ())",
            ])

        if "TABLESAMPLE" in kw:
            statements.extend([
                "SELECT a FROM t TABLESAMPLE BERNOULLI(10)",
                "SELECT a FROM t TABLESAMPLE SYSTEM(10)",
            ])

        if "WITHIN" in kw:
            statements.append("SELECT LISTAGG(a, ',') WITHIN GROUP (ORDER BY a) FROM t")

        if "OVER" in kw:
            pass  # already covered

        if "PIVOT" in kw:
            statements.append("SELECT * FROM t PIVOT (SUM(a) FOR b IN ('x', 'y'))")

        if "UNPIVOT" in kw:
            statements.append("SELECT * FROM t UNPIVOT (val FOR col IN (a, b, c))")

        if "RECURSIVE" in kw:
            pass  # already covered

        if "ON" in kw and "CONFLICT" in kw:
            pass  # already covered

        if "MATCHED" in kw:
            pass  # already covered

        if "VACUUM" in kw:
            statements.append("VACUUM")

        if "ANALYZE" in kw:
            statements.append("ANALYZE t")

        if "REINDEX" in kw:
            statements.append("REINDEX TABLE t")

        if "CLUSTER" in kw:
            statements.append("CLUSTER t USING idx")

        if "COPY" in kw:
            statements.append("COPY t FROM 'file.csv'")

        if "SHOW" in kw:
            statements.append("SHOW ALL")

        if "LISTEN" in kw:
            statements.append("LISTEN channel1")

        if "NOTIFY" in kw:
            statements.append("NOTIFY channel1")

        if "LOCK" in kw:
            statements.append("LOCK TABLE t")

        if "PREPARE" in kw:
            statements.append("PREPARE stmt AS SELECT a FROM t WHERE a = $1")

        if "EXECUTE" in kw:
            statements.append("EXECUTE stmt(1)")

        if "DEALLOCATE" in kw:
            statements.append("DEALLOCATE stmt")

        if "DECLARE" in kw:
            statements.append("DECLARE cur CURSOR FOR SELECT a FROM t")

        if "FETCH" in kw and "CURSOR" in kw:
            statements.append("FETCH NEXT FROM cur")

        if "CLOSE" in kw:
            statements.append("CLOSE cur")

        if "SET" in kw:
            pass  # already covered

        if "SCHEMA" in kw:
            statements.extend([
                "CREATE SCHEMA myschema",
                "DROP SCHEMA myschema",
                "DROP SCHEMA IF EXISTS myschema CASCADE",
            ])

        if "DATABASE" in kw:
            statements.extend([
                "CREATE DATABASE mydb",
                "DROP DATABASE mydb",
                "DROP DATABASE IF EXISTS mydb",
            ])

        if "SEQUENCE" in kw:
            statements.extend([
                "CREATE SEQUENCE seq",
                "CREATE SEQUENCE seq START WITH 1 INCREMENT BY 1",
                "DROP SEQUENCE seq",
                "ALTER SEQUENCE seq RESTART WITH 1",
            ])

        if "TRIGGER" in kw:
            statements.extend([
                "CREATE TRIGGER trig BEFORE INSERT ON t FOR EACH ROW EXECUTE PROCEDURE func()",
                "DROP TRIGGER trig ON t",
            ])

        if "FUNCTION" in kw or "PROCEDURE" in kw:
            statements.extend([
                "CREATE FUNCTION func() RETURNS INT AS $$ SELECT 1 $$ LANGUAGE sql",
                "DROP FUNCTION func",
            ])

        if "TYPE" in kw and "CREATE" in kw:
            statements.append("CREATE TYPE mytype AS (a INT, b TEXT)")

        if "COMMENT" in kw:
            statements.append("COMMENT ON TABLE t IS 'test table'")

        if "DOMAIN" in kw:
            statements.append("CREATE DOMAIN positive_int AS INT CHECK (VALUE > 0)")

        return statements
