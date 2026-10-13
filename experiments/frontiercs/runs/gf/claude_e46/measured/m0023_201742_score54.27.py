import os
import re

class Solution:
    def solve(self, resources_path: str) -> list[str]:
        parser_src = self._read(os.path.join(resources_path, "sql_engine", "parser.py"))
        tokenizer_src = self._read(os.path.join(resources_path, "sql_engine", "tokenizer.py"))
        ast_src = self._read(os.path.join(resources_path, "sql_engine", "ast_nodes.py"))

        stmts = list(self._comprehensive_stmts())

        if parser_src:
            extras = self._from_parser_analysis(parser_src, tokenizer_src, ast_src)
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

    def _from_parser_analysis(self, parser_src, tokenizer_src, ast_src):
        extras = []
        src = parser_src + "\n" + tokenizer_src

        # Extract all string literals that appear in comparisons
        # Patterns: == 'KEYWORD', == "KEYWORD", in ('K1', 'K2'), .type == 'X'
        keywords = set()
        for m in re.finditer(r"""[=!]=\s*['"]([A-Z_]+)['"]""", src):
            keywords.add(m.group(1))
        for m in re.finditer(r"""['"]([A-Z_]+)['"]\s*[=!]=""", src):
            keywords.add(m.group(1))
        for m in re.finditer(r"""in\s*\(([^)]+)\)""", src):
            for m2 in re.finditer(r"""['"]([A-Z_]+)['"]""", m.group(1)):
                keywords.add(m2.group(1))
        for m in re.finditer(r"""in\s*\{([^}]+)\}""", src):
            for m2 in re.finditer(r"""['"]([A-Z_]+)['"]""", m.group(1)):
                keywords.add(m2.group(1))
        for m in re.finditer(r"""\.value\s*==\s*['"]([^'"]+)['"]""", src):
            keywords.add(m.group(1))
        for m in re.finditer(r"""['"]([^'"]+)['"]\s*:\s*""", src):
            if m.group(1).isupper() and len(m.group(1)) <= 20:
                keywords.add(m.group(1))

        # Extract parse method names
        methods = set()
        for m in re.finditer(r'def\s+(parse_\w+)', parser_src):
            methods.add(m.group(1))

        # Map keywords to SQL statements
        kw_map = {
            'ILIKE': "SELECT a FROM t WHERE a ILIKE '%x%'",
            'SIMILAR': "SELECT a FROM t WHERE a SIMILAR TO '%x%'",
            'GLOB': "SELECT a FROM t WHERE a GLOB '*x*'",
            'REGEXP': "SELECT a FROM t WHERE a REGEXP '^[0-9]+'",
            'REPLACE': "REPLACE INTO t (a) VALUES (1)",
            'UPSERT': "INSERT INTO t (a) VALUES (1) ON CONFLICT (a) DO UPDATE SET a = 1",
            'ON': "SELECT a FROM t1 JOIN t2 ON t1.id = t2.id",
            'CONFLICT': "INSERT INTO t (a) VALUES (1) ON CONFLICT DO NOTHING",
            'DO': "INSERT INTO t (a) VALUES (1) ON CONFLICT DO NOTHING",
            'NOTHING': "INSERT INTO t (a) VALUES (1) ON CONFLICT DO NOTHING",
            'RETURNING': "INSERT INTO t (a) VALUES (1) RETURNING *",
            'MERGE': "MERGE INTO t1 USING t2 ON t1.id = t2.id WHEN MATCHED THEN UPDATE SET a = t2.a WHEN NOT MATCHED THEN INSERT (a) VALUES (t2.a)",
            'WHEN': "SELECT CASE WHEN a = 1 THEN 'y' END FROM t",
            'MATCHED': "MERGE INTO t1 USING t2 ON t1.id = t2.id WHEN MATCHED THEN UPDATE SET a = t2.a",
            'LATERAL': "SELECT * FROM t1, LATERAL (SELECT * FROM t2 WHERE t2.id = t1.id) AS sub",
            'GROUPING': "SELECT a, GROUPING(a) FROM t GROUP BY GROUPING SETS ((a), ())",
            'CUBE': "SELECT a, b, SUM(c) FROM t GROUP BY CUBE (a, b)",
            'ROLLUP': "SELECT a, b, SUM(c) FROM t GROUP BY ROLLUP (a, b)",
            'SETS': "SELECT a, SUM(b) FROM t GROUP BY GROUPING SETS ((a), ())",
            'FETCH': "SELECT a FROM t ORDER BY a FETCH FIRST 10 ROWS ONLY",
            'ROWS': "SELECT a FROM t ORDER BY a FETCH FIRST 5 ROWS ONLY",
            'ONLY': "SELECT a FROM t ORDER BY a FETCH FIRST 5 ROWS ONLY",
            'FIRST': "SELECT FIRST_VALUE(a) OVER (ORDER BY a) FROM t",
            'LAST': "SELECT LAST_VALUE(a) OVER (ORDER BY a) FROM t",
            'FILTER': "SELECT COUNT(*) FILTER (WHERE a > 0) FROM t",
            'WITHIN': "SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY a) FROM t",
            'WINDOW': "SELECT a, SUM(b) OVER w FROM t WINDOW w AS (ORDER BY a)",
            'PARTITION': "SELECT SUM(a) OVER (PARTITION BY b) FROM t",
            'PRECEDING': "SELECT SUM(a) OVER (ORDER BY b ROWS BETWEEN 1 PRECEDING AND CURRENT ROW) FROM t",
            'FOLLOWING': "SELECT SUM(a) OVER (ORDER BY b ROWS BETWEEN CURRENT ROW AND 1 FOLLOWING) FROM t",
            'UNBOUNDED': "SELECT SUM(a) OVER (ORDER BY b ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) FROM t",
            'CURRENT': "SELECT CURRENT_DATE, CURRENT_TIME, CURRENT_TIMESTAMP",
            'POSITION': "SELECT POSITION('x' IN a) FROM t",
            'OVERLAY': "SELECT OVERLAY(a PLACING 'x' FROM 1 FOR 2) FROM t",
            'EXTRACT': "SELECT EXTRACT(YEAR FROM a) FROM t",
            'YEAR': "SELECT EXTRACT(YEAR FROM d) FROM t",
            'MONTH': "SELECT EXTRACT(MONTH FROM d) FROM t",
            'DAY': "SELECT EXTRACT(DAY FROM d) FROM t",
            'HOUR': "SELECT EXTRACT(HOUR FROM d) FROM t",
            'MINUTE': "SELECT EXTRACT(MINUTE FROM d) FROM t",
            'SECOND': "SELECT EXTRACT(SECOND FROM d) FROM t",
            'COLLATE': "SELECT a COLLATE \"en_US\" FROM t",
            'TABLESAMPLE': "SELECT * FROM t TABLESAMPLE BERNOULLI(10)",
            'BERNOULLI': "SELECT * FROM t TABLESAMPLE BERNOULLI(10)",
            'SYSTEM': "SELECT * FROM t TABLESAMPLE SYSTEM(10)",
            'GENERATED': "CREATE TABLE t (a INT GENERATED ALWAYS AS IDENTITY)",
            'IDENTITY': "CREATE TABLE t (a INT GENERATED ALWAYS AS IDENTITY)",
            'ALWAYS': "CREATE TABLE t (a INT GENERATED ALWAYS AS IDENTITY)",
            'SERIAL': "CREATE TABLE t (a SERIAL PRIMARY KEY)",
            'BIGSERIAL': "CREATE TABLE t (a BIGSERIAL)",
            'SMALLSERIAL': "CREATE TABLE t (a SMALLSERIAL)",
            'CASCADE': "DROP TABLE t CASCADE",
            'RESTRICT': "DROP TABLE t RESTRICT",
            'TEMP': "CREATE TEMP TABLE t (a INT)",
            'TEMPORARY': "CREATE TEMPORARY TABLE t (a INT)",
            'UNLOGGED': "CREATE UNLOGGED TABLE t (a INT)",
            'MATERIALIZED': "CREATE MATERIALIZED VIEW mv AS SELECT a FROM t",
            'REFRESH': "REFRESH MATERIALIZED VIEW mv",
            'VACUUM': "VACUUM t",
            'ANALYZE': "ANALYZE t",
            'REINDEX': "REINDEX TABLE t",
            'CLUSTER': "CLUSTER t USING idx",
            'COPY': "COPY t FROM '/tmp/data.csv' WITH (FORMAT CSV)",
            'FORMAT': "COPY t FROM '/tmp/data.csv' WITH (FORMAT CSV)",
            'CSV': "COPY t FROM '/tmp/data.csv' WITH (FORMAT CSV)",
            'DELIMITER': "COPY t FROM '/tmp/data.csv' WITH (DELIMITER ',')",
            'SCHEMA': "CREATE SCHEMA s",
            'DATABASE': "CREATE DATABASE d",
            'TYPE': "CREATE TYPE mood AS ENUM ('happy', 'sad')",
            'ENUM': "CREATE TYPE mood AS ENUM ('happy', 'sad')",
            'DOMAIN': "CREATE DOMAIN posint AS INT CHECK (VALUE > 0)",
            'SEQUENCE': "CREATE SEQUENCE seq START 1",
            'FUNCTION': "CREATE FUNCTION f() RETURNS INT AS $$ SELECT 1 $$ LANGUAGE SQL",
            'PROCEDURE': "CREATE PROCEDURE p() AS $$ SELECT 1 $$ LANGUAGE SQL",
            'TRIGGER': "CREATE TRIGGER tr BEFORE INSERT ON t FOR EACH ROW EXECUTE FUNCTION f()",
            'BEFORE': "CREATE TRIGGER tr BEFORE INSERT ON t FOR EACH ROW EXECUTE FUNCTION f()",
            'AFTER': "CREATE TRIGGER tr AFTER INSERT ON t FOR EACH ROW EXECUTE FUNCTION f()",
            'EXECUTE': "EXECUTE stmt",
            'PREPARE': "PREPARE stmt AS SELECT a FROM t WHERE a = $1",
            'DEALLOCATE': "DEALLOCATE stmt",
            'LISTEN': "LISTEN channel",
            'NOTIFY': "NOTIFY channel",
            'UNLISTEN': "UNLISTEN channel",
            'LOCK': "LOCK TABLE t IN ACCESS EXCLUSIVE MODE",
            'SHARE': "SELECT a FROM t FOR SHARE",
            'EXCLUSIVE': "LOCK TABLE t IN EXCLUSIVE MODE",
            'ACCESS': "LOCK TABLE t IN ACCESS SHARE MODE",
            'NO': "INSERT INTO t (a) VALUES (1) ON CONFLICT DO NOTHING",
            'ACTION': "CREATE TABLE t (a INT REFERENCES other(id) ON DELETE NO ACTION)",
            'DEFERRABLE': "CREATE TABLE t (a INT UNIQUE DEFERRABLE INITIALLY DEFERRED)",
            'DEFERRED': "SET CONSTRAINTS ALL DEFERRED",
            'IMMEDIATE': "SET CONSTRAINTS ALL IMMEDIATE",
            'INITIALLY': "CREATE TABLE t (a INT UNIQUE DEFERRABLE INITIALLY IMMEDIATE)",
            'CONSTRAINT': "ALTER TABLE t ADD CONSTRAINT c CHECK (a > 0)",
            'FOREIGN': "ALTER TABLE t ADD CONSTRAINT fk FOREIGN KEY (a) REFERENCES other(id)",
            'REFERENCES': "CREATE TABLE t (a INT REFERENCES other(id))",
            'CONCURRENTLY': "CREATE INDEX CONCURRENTLY idx ON t (a)",
            'USING': "CREATE INDEX idx ON t USING btree (a)",
            'BTREE': "CREATE INDEX idx ON t USING btree (a)",
            'HASH': "CREATE INDEX idx ON t USING hash (a)",
            'GIN': "CREATE INDEX idx ON t USING gin (a)",
            'GIST': "CREATE INDEX idx ON t USING gist (a)",
            'INCLUDE': "CREATE INDEX idx ON t (a) INCLUDE (b)",
            'WHERE_IDX': "CREATE INDEX idx ON t (a) WHERE a > 0",
            'NULLS': "SELECT a FROM t ORDER BY a NULLS FIRST",
            'RECURSIVE': "WITH RECURSIVE cte AS (SELECT 1 AS n UNION ALL SELECT n+1 FROM cte WHERE n<10) SELECT * FROM cte",
            'OVER': "SELECT ROW_NUMBER() OVER (ORDER BY a) FROM t",
            'VALUES': "VALUES (1, 2), (3, 4)",
            'DEFAULT': "INSERT INTO t DEFAULT VALUES",
            'TABLE': "TABLE t",
            'LIKE_TABLE': "CREATE TABLE t2 (LIKE t INCLUDING ALL)",
            'INCLUDING': "CREATE TABLE t2 (LIKE t INCLUDING ALL)",
            'EXCLUDING': "CREATE TABLE t2 (LIKE t EXCLUDING INDEXES)",
            'INHERITS': "CREATE TABLE child () INHERITS (parent)",
            'OF': "ALTER TABLE t OWNER TO user1",
            'OWNER': "ALTER TABLE t OWNER TO user1",
            'IF': "CREATE TABLE IF NOT EXISTS t (a INT)",
            'EXISTS': "SELECT a FROM t WHERE EXISTS (SELECT 1 FROM t2)",
            'SOME': "SELECT a FROM t WHERE a > SOME (SELECT b FROM t2)",
            'ANY': "SELECT a FROM t WHERE a > ANY (SELECT b FROM t2)",
            'ALL': "SELECT a FROM t WHERE a > ALL (SELECT b FROM t2)",
            'ARRAY': "SELECT ARRAY[1, 2, 3]",
            'ROW': "SELECT ROW(1, 2, 3)",
            'GREATEST': "SELECT GREATEST(1, 2, 3)",
            'LEAST': "SELECT LEAST(1, 2, 3)",
            'BETWEEN': "SELECT a FROM t WHERE a BETWEEN 1 AND 10",
            'LIKE': "SELECT a FROM t WHERE a LIKE '%x%'",
            'ESCAPE': "SELECT a FROM t WHERE a LIKE '%x%' ESCAPE '\\'",
            'CAST': "SELECT CAST(a AS INT) FROM t",
            'DOUBLE': "CREATE TABLE t (a DOUBLE PRECISION)",
            'PRECISION': "CREATE TABLE t (a DOUBLE PRECISION)",
            'NUMERIC': "CREATE TABLE t (a NUMERIC(10, 2))",
            'SMALLINT': "CREATE TABLE t (a SMALLINT)",
            'BIGINT': "CREATE TABLE t (a BIGINT)",
            'BLOB': "CREATE TABLE t (a BLOB)",
            'CLOB': "CREATE TABLE t (a CLOB)",
            'BINARY': "CREATE TABLE t (a BINARY(10))",
            'VARBINARY': "CREATE TABLE t (a VARBINARY(100))",
            'BIT': "CREATE TABLE t (a BIT(1))",
            'INTERVAL': "SELECT INTERVAL '1 day'",
            'JSON': "CREATE TABLE t (a JSON)",
            'JSONB': "CREATE TABLE t (a JSONB)",
            'XML': "CREATE TABLE t (a XML)",
            'UUID': "CREATE TABLE t (a UUID DEFAULT gen_random_uuid())",
            'INET': "CREATE TABLE t (a INET)",
            'CIDR': "CREATE TABLE t (a CIDR)",
            'MACADDR': "CREATE TABLE t (a MACADDR)",
            'MONEY': "CREATE TABLE t (a MONEY)",
            'TSVECTOR': "CREATE TABLE t (a TSVECTOR)",
            'TSQUERY': "CREATE TABLE t (a TSQUERY)",
            'VARYING': "CREATE TABLE t (a CHARACTER VARYING(100))",
            'CHARACTER': "CREATE TABLE t (a CHARACTER VARYING(100))",
        }

        for kw in keywords:
            if kw in kw_map:
                extras.append(kw_map[kw])

        # If parser has specific parse methods, generate SQL for them
        method_map = {
            'parse_select': "SELECT a FROM t",
            'parse_insert': "INSERT INTO t (a) VALUES (1)",
            'parse_update': "UPDATE t SET a = 1",
            'parse_delete': "DELETE FROM t",
            'parse_create': "CREATE TABLE t (a INT)",
            'parse_create_table': "CREATE TABLE t (a INT)",
            'parse_create_index': "CREATE INDEX idx ON t (a)",
            'parse_create_view': "CREATE VIEW v AS SELECT a FROM t",
            'parse_drop': "DROP TABLE t",
            'parse_drop_table': "DROP TABLE t",
            'parse_drop_index': "DROP INDEX idx",
            'parse_alter': "ALTER TABLE t ADD COLUMN a INT",
            'parse_alter_table': "ALTER TABLE t ADD COLUMN a INT",
            'parse_grant': "GRANT SELECT ON t TO user1",
            'parse_revoke': "REVOKE SELECT ON t FROM user1",
            'parse_begin': "BEGIN",
            'parse_commit': "COMMIT",
            'parse_rollback': "ROLLBACK",
            'parse_savepoint': "SAVEPOINT sp1",
            'parse_explain': "EXPLAIN SELECT a FROM t",
            'parse_truncate': "TRUNCATE TABLE t",
            'parse_set': "SET search_path TO public",
            'parse_merge': "MERGE INTO t1 USING t2 ON t1.id = t2.id WHEN MATCHED THEN UPDATE SET a = t2.a WHEN NOT MATCHED THEN INSERT (a) VALUES (t2.a)",
            'parse_with': "WITH cte AS (SELECT a FROM t) SELECT * FROM cte",
            'parse_cte': "WITH cte AS (SELECT a FROM t) SELECT * FROM cte",
            'parse_expression': "SELECT 1 + 2 * 3",
            'parse_where': "SELECT a FROM t WHERE a = 1",
            'parse_join': "SELECT a FROM t1 JOIN t2 ON t1.id = t2.id",
            'parse_order': "SELECT a FROM t ORDER BY a",
            'parse_order_by': "SELECT a FROM t ORDER BY a",
            'parse_group': "SELECT a, COUNT(*) FROM t GROUP BY a",
            'parse_group_by': "SELECT a, COUNT(*) FROM t GROUP BY a",
            'parse_having': "SELECT a, COUNT(*) FROM t GROUP BY a HAVING COUNT(*) > 1",
            'parse_limit': "SELECT a FROM t LIMIT 10",
            'parse_union': "SELECT a FROM t1 UNION SELECT b FROM t2",
            'parse_case': "SELECT CASE WHEN a = 1 THEN 'y' ELSE 'n' END FROM t",
            'parse_function': "SELECT UPPER(a) FROM t",
            'parse_function_call': "SELECT UPPER(a) FROM t",
            'parse_window': "SELECT SUM(a) OVER (ORDER BY b) FROM t",
            'parse_window_function': "SELECT ROW_NUMBER() OVER (ORDER BY a) FROM t",
            'parse_subquery': "SELECT a FROM (SELECT b FROM t) AS sub",
            'parse_between': "SELECT a FROM t WHERE a BETWEEN 1 AND 10",
            'parse_in': "SELECT a FROM t WHERE a IN (1, 2, 3)",
            'parse_like': "SELECT a FROM t WHERE a LIKE '%x%'",
            'parse_is': "SELECT a FROM t WHERE a IS NULL",
            'parse_exists': "SELECT a FROM t WHERE EXISTS (SELECT 1 FROM t2)",
            'parse_column_def': "CREATE TABLE t (a INT NOT NULL DEFAULT 0)",
            'parse_constraint': "ALTER TABLE t ADD CONSTRAINT c CHECK (a > 0)",
            'parse_type': "SELECT CAST(a AS VARCHAR(100)) FROM t",
            'parse_data_type': "CREATE TABLE t (a DECIMAL(10, 2))",
            'parse_values': "INSERT INTO t (a) VALUES (1), (2)",
            'parse_returning': "INSERT INTO t (a) VALUES (1) RETURNING *",
            'parse_on_conflict': "INSERT INTO t (a) VALUES (1) ON CONFLICT (a) DO UPDATE SET a = 1",
            'parse_copy': "COPY t FROM '/tmp/data.csv'",
            'parse_vacuum': "VACUUM t",
            'parse_analyze': "ANALYZE t",
            'parse_prepare': "PREPARE stmt AS SELECT a FROM t WHERE a = $1",
            'parse_execute': "EXECUTE stmt",
            'parse_deallocate': "DEALLOCATE stmt",
            'parse_lock': "LOCK TABLE t",
            'parse_listen': "LISTEN channel",
            'parse_notify': "NOTIFY channel",
            'parse_show': "SHOW search_path",
            'parse_reset': "RESET search_path",
            'parse_discard': "DISCARD ALL",
            'parse_comment': "COMMENT ON TABLE t IS 'test'",
            'parse_create_schema': "CREATE SCHEMA s",
            'parse_create_database': "CREATE DATABASE d",
            'parse_create_type': "CREATE TYPE mood AS ENUM ('happy', 'sad')",
            'parse_create_sequence': "CREATE SEQUENCE seq START 1",
            'parse_create_function': "CREATE FUNCTION f() RETURNS INT AS $$ SELECT 1 $$ LANGUAGE SQL",
            'parse_create_trigger': "CREATE TRIGGER tr BEFORE INSERT ON t FOR EACH ROW EXECUTE FUNCTION f()",
        }

        for method_name in methods:
            if method_name in method_map:
                extras.append(method_map[method_name])

        return extras

    def _comprehensive_stmts(self):
        return [
            # SELECT basics
            "SELECT 1",
            "SELECT a, b, c FROM t",
            "SELECT * FROM t",
            "SELECT DISTINCT a FROM t",
            "SELECT ALL a FROM t",
            "SELECT a AS x, b AS y FROM t AS z",
            "SELECT t.a, t.* FROM t",

            # WHERE - comparison operators
            "SELECT a FROM t WHERE a = 1",
            "SELECT a FROM t WHERE a != 1",
            "SELECT a FROM t WHERE a <> 1",
            "SELECT a FROM t WHERE a > 1",
            "SELECT a FROM t WHERE a < 1",
            "SELECT a FROM t WHERE a >= 1",
            "SELECT a FROM t WHERE a <= 1",

            # WHERE - pattern matching
            "SELECT a FROM t WHERE a LIKE '%test%'",
            "SELECT a FROM t WHERE a NOT LIKE 'test%'",
            "SELECT a FROM t WHERE a ILIKE '%x%'",
            "SELECT a FROM t WHERE a SIMILAR TO '%x%'",
            "SELECT a FROM t WHERE a LIKE '%x%' ESCAPE '\\'",

            # WHERE - IN, BETWEEN, IS
            "SELECT a FROM t WHERE a IN (1, 2, 3)",
            "SELECT a FROM t WHERE a NOT IN (1, 2)",
            "SELECT a FROM t WHERE a BETWEEN 1 AND 10",
            "SELECT a FROM t WHERE a NOT BETWEEN 1 AND 10",
            "SELECT a FROM t WHERE a IS NULL",
            "SELECT a FROM t WHERE a IS NOT NULL",

            # WHERE - logical
            "SELECT a FROM t WHERE a = 1 AND b = 2",
            "SELECT a FROM t WHERE a = 1 OR b = 2",
            "SELECT a FROM t WHERE NOT a = 1",
            "SELECT a FROM t WHERE (a = 1 OR b = 2) AND c = 3",

            # Arithmetic + string ops
            "SELECT a + b, a - b, a * b, a / b, a % b, -a, +a FROM t",
            "SELECT 'hello', 3.14, -3.14, 0, TRUE, FALSE, NULL",
            "SELECT a || b FROM t",
            "SELECT (1 + 2) * 3",

            # Aggregates + GROUP BY + HAVING
            "SELECT COUNT(*), COUNT(a), COUNT(DISTINCT a), SUM(a), AVG(a), MIN(a), MAX(a) FROM t",
            "SELECT a, COUNT(*) FROM t GROUP BY a HAVING COUNT(*) > 1",
            "SELECT a, b, SUM(c) FROM t GROUP BY a, b",

            # ORDER BY, LIMIT
            "SELECT a FROM t ORDER BY a ASC, b DESC",
            "SELECT a FROM t ORDER BY 1",
            "SELECT a FROM t ORDER BY a NULLS FIRST",
            "SELECT a FROM t ORDER BY a NULLS LAST",
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
            "SELECT a FROM t1 JOIN t2 ON t1.id = t2.id JOIN t3 ON t2.id = t3.id",

            # Subqueries
            "SELECT a FROM (SELECT b FROM t) AS sub",
            "SELECT a FROM t WHERE a IN (SELECT b FROM t2)",
            "SELECT a FROM t WHERE EXISTS (SELECT 1 FROM t2 WHERE t2.id = t.id)",
            "SELECT a FROM t WHERE NOT EXISTS (SELECT 1 FROM t2)",
            "SELECT (SELECT MAX(a) FROM t2) AS m FROM t",
            "SELECT a FROM t WHERE a > ANY (SELECT b FROM t2)",
            "SELECT a FROM t WHERE a > ALL (SELECT b FROM t2)",
            "SELECT a FROM t WHERE a > SOME (SELECT b FROM t2)",

            # Set operations
            "SELECT a FROM t1 UNION SELECT b FROM t2",
            "SELECT a FROM t1 UNION ALL SELECT b FROM t2",
            "SELECT a FROM t1 INTERSECT SELECT b FROM t2",
            "SELECT a FROM t1 INTERSECT ALL SELECT b FROM t2",
            "SELECT a FROM t1 EXCEPT SELECT b FROM t2",
            "SELECT a FROM t1 EXCEPT ALL SELECT b FROM t2",

            # INSERT
            "INSERT INTO t (a, b) VALUES (1, 2)",
            "INSERT INTO t VALUES (1, 2, 3)",
            "INSERT INTO t (a) VALUES (1), (2), (3)",
            "INSERT INTO t SELECT a FROM t2",
            "INSERT INTO t DEFAULT VALUES",
            "INSERT INTO t (a) VALUES (1) RETURNING *",
            "INSERT INTO t (a) VALUES (1) RETURNING a, b",
            "INSERT INTO t (a) VALUES (1) ON CONFLICT (a) DO UPDATE SET a = 1",
            "INSERT INTO t (a) VALUES (1) ON CONFLICT (a) DO NOTHING",
            "INSERT INTO t (a) VALUES (1) ON CONFLICT DO NOTHING",

            # UPDATE
            "UPDATE t SET a = 1, b = 2 WHERE c = 3",
            "UPDATE t SET a = a + 1",
            "UPDATE t SET a = 1 RETURNING *",

            # DELETE
            "DELETE FROM t WHERE a = 1",
            "DELETE FROM t",
            "DELETE FROM t RETURNING *",

            # CREATE TABLE with various types and constraints
            "CREATE TABLE t (a INT PRIMARY KEY, b VARCHAR(255) NOT NULL, c FLOAT DEFAULT 0.0, d BOOLEAN, e DATE, f TIMESTAMP, g TEXT UNIQUE)",
            "CREATE TABLE IF NOT EXISTS t (a INT)",
            "CREATE TABLE t (a INT, b INT, PRIMARY KEY (a, b))",
            "CREATE TABLE t (a INT REFERENCES other(id))",
            "CREATE TABLE t (a INT REFERENCES other(id) ON DELETE CASCADE ON UPDATE SET NULL)",
            "CREATE TABLE t (a INT CHECK (a > 0))",
            "CREATE TABLE t (a DECIMAL(10, 2), b INTEGER, c REAL, d CHAR(10), e VARCHAR(100))",
            "CREATE TABLE t (a SMALLINT, b BIGINT, c DOUBLE PRECISION, d NUMERIC(5))",
            "CREATE TABLE t (a SERIAL PRIMARY KEY)",
            "CREATE TABLE t (a BIGSERIAL)",
            "CREATE TEMP TABLE t (a INT)",
            "CREATE TABLE t (a INT GENERATED ALWAYS AS IDENTITY)",
            "CREATE TABLE t (a INT, CONSTRAINT ck CHECK (a > 0), CONSTRAINT uq UNIQUE (a))",

            # DROP
            "DROP TABLE t",
            "DROP TABLE IF EXISTS t",
            "DROP TABLE t CASCADE",
            "DROP TABLE t RESTRICT",

            # INDEX
            "CREATE INDEX idx ON t (a)",
            "CREATE UNIQUE INDEX idx ON t (a, b)",
            "CREATE INDEX IF NOT EXISTS idx ON t (a)",
            "CREATE INDEX idx ON t (a) WHERE a > 0",
            "CREATE INDEX CONCURRENTLY idx ON t (a)",
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
            "ALTER TABLE t ALTER COLUMN a TYPE VARCHAR(200)",
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
            "SELECT NOW(), CURRENT_TIMESTAMP, CURRENT_DATE, CURRENT_TIME",
            "SELECT POSITION('x' IN a) FROM t",
            "SELECT EXTRACT(YEAR FROM d) FROM t",
            "SELECT GREATEST(1, 2, 3), LEAST(1, 2, 3)",
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
            "SELECT SUM(b) OVER (ORDER BY a GROUPS BETWEEN 1 PRECEDING AND 1 FOLLOWING) FROM t",
            "SELECT COUNT(*) OVER () FROM t",
            "SELECT COUNT(*) FILTER (WHERE a > 0) FROM t",
            "SELECT a, SUM(b) OVER w FROM t WINDOW w AS (ORDER BY a)",

            # CTEs
            "WITH cte AS (SELECT a FROM t) SELECT * FROM cte",
            "WITH cte1 AS (SELECT a FROM t1), cte2 AS (SELECT b FROM t2) SELECT * FROM cte1 JOIN cte2 ON cte1.a = cte2.b",
            "WITH RECURSIVE cte AS (SELECT 1 AS n UNION ALL SELECT n + 1 FROM cte WHERE n < 10) SELECT * FROM cte",

            # DISTINCT ON
            "SELECT DISTINCT ON (a) a, b FROM t",

            # Type literals
            "SELECT DATE '2023-01-01'",
            "SELECT TIMESTAMP '2023-01-01 00:00:00'",
            "SELECT TIME '12:00:00'",
            "SELECT INTERVAL '1' DAY",

            # VIEW
            "CREATE VIEW v AS SELECT a FROM t",
            "CREATE OR REPLACE VIEW v AS SELECT a FROM t",
            "DROP VIEW v",
            "DROP VIEW IF EXISTS v",
            "CREATE MATERIALIZED VIEW mv AS SELECT a FROM t",

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

            # SET / SHOW / RESET
            "SET search_path TO public",
            "SET search_path = 'public'",
            "SHOW search_path",
            "RESET search_path",
            "RESET ALL",

            # GRANT / REVOKE
            "GRANT SELECT ON t TO user1",
            "GRANT ALL ON t TO user1",
            "GRANT SELECT, INSERT, UPDATE ON t TO user1",
            "REVOKE SELECT ON t FROM user1",
            "REVOKE ALL ON t FROM user1",

            # Locking
            "SELECT a FROM t FOR UPDATE",
            "SELECT a FROM t FOR SHARE",
            "SELECT a FROM t FOR NO KEY UPDATE",
            "SELECT a FROM t FOR KEY SHARE",
            "LOCK TABLE t IN ACCESS SHARE MODE",
            "LOCK TABLE t IN EXCLUSIVE MODE",

            # TRUNCATE
            "TRUNCATE TABLE t",
            "TRUNCATE TABLE t CASCADE",
            "TRUNCATE TABLE t RESTART IDENTITY",

            # FETCH FIRST
            "SELECT a FROM t ORDER BY a FETCH FIRST 5 ROWS ONLY",
            "SELECT a FROM t FETCH NEXT 1 ROW ONLY",

            # GROUPING SETS / CUBE / ROLLUP
            "SELECT a, b, SUM(c) FROM t GROUP BY GROUPING SETS ((a), (b), ())",
            "SELECT a, b, SUM(c) FROM t GROUP BY CUBE (a, b)",
            "SELECT a, b, SUM(c) FROM t GROUP BY ROLLUP (a, b)",

            # LATERAL
            "SELECT * FROM t1, LATERAL (SELECT * FROM t2 WHERE t2.id = t1.id) AS sub",

            # VALUES as statement
            "VALUES (1, 'a'), (2, 'b')",

            # TABLE statement
            "TABLE t",

            # MERGE
            "MERGE INTO t1 USING t2 ON t1.id = t2.id WHEN MATCHED THEN UPDATE SET a = t2.a WHEN NOT MATCHED THEN INSERT (a) VALUES (t2.a)",

            # COPY
            "COPY t TO STDOUT",
            "COPY t FROM STDIN",

            # Array, Row
            "SELECT ARRAY[1, 2, 3]",
            "SELECT ROW(1, 2, 3)",
            "SELECT a[1] FROM t",

            # Type cast
            "SELECT a::INT FROM t",
            "SELECT a::VARCHAR(100) FROM t",

            # PREPARE / EXECUTE / DEALLOCATE
            "PREPARE stmt AS SELECT a FROM t WHERE a = $1",
            "EXECUTE stmt(1)",
            "DEALLOCATE stmt",

            # COMMENT
            "COMMENT ON TABLE t IS 'test'",
            "COMMENT ON COLUMN t.a IS 'test'",

            # Schema operations
            "CREATE SCHEMA s",
            "DROP SCHEMA s",
            "DROP SCHEMA IF EXISTS s CASCADE",

            # VACUUM / ANALYZE / REINDEX
            "VACUUM",
            "VACUUM t",
            "ANALYZE t",
            "REINDEX TABLE t",

            # DISCARD
            "DISCARD ALL",

            # LISTEN / NOTIFY / UNLISTEN
            "LISTEN channel1",
            "NOTIFY channel1",
            "UNLISTEN channel1",

            # SET CONSTRAINTS
            "SET CONSTRAINTS ALL DEFERRED",
            "SET CONSTRAINTS ALL IMMEDIATE",

            # DO block
            "DO $$ BEGIN RAISE NOTICE 'test'; END $$",

            # REPLACE
            "REPLACE INTO t (a) VALUES (1)",

            # Misc edge cases
            "SELECT a FROM t WHERE a = 1 LIMIT 1 FOR UPDATE",
            "SELECT 1 WHERE TRUE",
            "SELECT 1 WHERE FALSE",
            "SELECT 1 UNION SELECT 2 UNION SELECT 3",
            "SELECT a FROM t WHERE a = ANY(ARRAY[1, 2, 3])",
            "SELECT COALESCE(NULL, NULL, 1)",
            "SELECT NULLIF(1, 1)",
            "SELECT CASE WHEN TRUE THEN 1 END",
        ]
