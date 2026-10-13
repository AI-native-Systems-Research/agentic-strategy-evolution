import os
import re
import random

class Solution:
    def solve(self, resources_path: str) -> list[str]:
        grammar_path = os.path.join(resources_path, "sql_grammar.txt")
        parser_path = os.path.join(resources_path, "sql_engine", "parser.py")
        tokenizer_path = os.path.join(resources_path, "sql_engine", "tokenizer.py")

        grammar_src = ""
        parser_src = ""
        tokenizer_src = ""
        try:
            with open(grammar_path) as f:
                grammar_src = f.read()
        except:
            pass
        try:
            with open(parser_path) as f:
                parser_src = f.read()
        except:
            pass
        try:
            with open(tokenizer_path) as f:
                tokenizer_src = f.read()
        except:
            pass

        # Parse grammar to understand structure
        rules = self._parse_grammar(grammar_src)

        # Generate statements from grammar
        grammar_stmts = self._generate_from_grammar(rules) if rules else []

        # Also include hand-crafted statements for coverage
        hand_stmts = self._hand_crafted(parser_src)

        # Combine, deduplicate
        seen = set()
        result = []
        for s in grammar_stmts + hand_stmts:
            s = s.strip()
            if s and s not in seen:
                seen.add(s)
                result.append(s)

        return result

    def _parse_grammar(self, src):
        """Parse BNF-style grammar into rules dict."""
        if not src:
            return {}

        rules = {}
        current_rule = None

        for line in src.split('\n'):
            line = line.rstrip()

            # Match rule definition: <rule_name> ::= ...
            m = re.match(r'\s*<(\w[\w_-]*)>\s*::=\s*(.*)', line)
            if m:
                current_rule = m.group(1)
                rhs = m.group(2).strip()
                if current_rule not in rules:
                    rules[current_rule] = []
                if rhs:
                    rules[current_rule].append(rhs)
                continue

            # Match continuation with |
            m = re.match(r'\s*\|\s*(.*)', line)
            if m and current_rule:
                rhs = m.group(1).strip()
                if rhs:
                    rules[current_rule].append(rhs)
                continue

            # Match indented continuation
            if current_rule and line.startswith('  ') and line.strip():
                stripped = line.strip()
                if stripped.startswith('|'):
                    stripped = stripped[1:].strip()
                if stripped:
                    rules[current_rule].append(stripped)

        return rules

    def _generate_from_grammar(self, rules):
        """Generate SQL by expanding grammar rules with DFS."""
        stmts = []

        # Find the top-level rule (usually 'statement' or 'sql')
        top_rules = []
        for name in ['statement', 'sql', 'sql_statement', 'query', 'sql-statement',
                      'statements', 'program', 'start']:
            if name in rules:
                top_rules.append(name)

        if not top_rules:
            # Use all rules that don't appear on RHS
            rhs_refs = set()
            for alts in rules.values():
                for alt in alts:
                    for m in re.finditer(r'<(\w[\w_-]*)>', alt):
                        rhs_refs.add(m.group(1))
            for name in rules:
                if name not in rhs_refs:
                    top_rules.append(name)

        if not top_rules:
            top_rules = list(rules.keys())[:1]

        # For each alternative of top-level rule, try to expand it
        random.seed(42)

        for top in top_rules:
            for alt in rules.get(top, []):
                # Try multiple expansions per alternative to cover different sub-alternatives
                for attempt in range(3):
                    random.seed(42 + attempt)
                    result = self._expand(alt, rules, depth=0, max_depth=12, attempt=attempt)
                    if result:
                        stmts.append(result)

        return stmts

    def _expand(self, pattern, rules, depth=0, max_depth=12, attempt=0):
        """Expand a grammar pattern into a concrete string."""
        if depth > max_depth:
            return ""

        result = []
        i = 0
        s = pattern

        while i < len(s):
            if s[i] == '<':
                # Find matching >
                j = s.index('>', i)
                ref = s[i+1:j]
                i = j + 1

                if ref in rules:
                    alts = rules[ref]
                    if alts:
                        # Pick an alternative based on attempt and depth
                        idx = (attempt + depth) % len(alts)
                        expanded = self._expand(alts[idx], rules, depth+1, max_depth, attempt)
                        result.append(expanded)
                    else:
                        result.append(ref)
                else:
                    result.append(ref)
            elif s[i] == '[':
                # Optional: [...]
                j = self._find_matching(s, i, '[', ']')
                if j > i:
                    inner = s[i+1:j]
                    if attempt % 2 == 0:  # Sometimes include, sometimes skip
                        expanded = self._expand(inner, rules, depth+1, max_depth, attempt)
                        result.append(expanded)
                    i = j + 1
                else:
                    result.append(s[i])
                    i += 1
            elif s[i] == '{':
                # Repetition: {...}
                j = self._find_matching(s, i, '{', '}')
                if j > i:
                    inner = s[i+1:j]
                    expanded = self._expand(inner, rules, depth+1, max_depth, attempt)
                    result.append(expanded)
                    i = j + 1
                else:
                    result.append(s[i])
                    i += 1
            elif s[i] == "'":
                # Quoted terminal
                j = s.index("'", i+1)
                result.append(s[i+1:j])
                i = j + 1
            elif s[i] == '"':
                j = s.index('"', i+1)
                result.append(s[i+1:j])
                i = j + 1
            else:
                # Collect regular text until next special char
                j = i
                while j < len(s) and s[j] not in '<[{"\'>':
                    j += 1
                text = s[i:j].strip()
                if text:
                    result.append(text)
                i = j

        return ' '.join(r for r in result if r)

    def _find_matching(self, s, start, open_ch, close_ch):
        """Find matching closing bracket."""
        depth = 0
        for i in range(start, len(s)):
            if s[i] == open_ch:
                depth += 1
            elif s[i] == close_ch:
                depth -= 1
                if depth == 0:
                    return i
        return -1

    def _hand_crafted(self, parser_src):
        """Hand-crafted SQL statements for comprehensive coverage."""
        stmts = [
            # Basic SELECT
            "SELECT 1",
            "SELECT a FROM t",
            "SELECT a, b, c FROM t",
            "SELECT * FROM t",
            "SELECT DISTINCT a FROM t",
            "SELECT ALL a FROM t",

            # Aliases
            "SELECT a AS x FROM t",
            "SELECT a AS x, b AS y FROM t AS z",
            "SELECT t.a FROM t",
            "SELECT t.* FROM t",

            # WHERE with all comparison operators
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

            # Logical operators
            "SELECT a FROM t WHERE a = 1 AND b = 2",
            "SELECT a FROM t WHERE a = 1 OR b = 2",
            "SELECT a FROM t WHERE NOT a = 1",
            "SELECT a FROM t WHERE (a = 1 OR b = 2) AND c = 3",

            # Arithmetic
            "SELECT a + b FROM t",
            "SELECT a - b FROM t",
            "SELECT a * b FROM t",
            "SELECT a / b FROM t",
            "SELECT a % b FROM t",
            "SELECT -a FROM t",
            "SELECT +a FROM t",

            # Literals
            "SELECT 'hello'",
            "SELECT 3.14",
            "SELECT -3.14",
            "SELECT 0",
            "SELECT TRUE, FALSE",
            "SELECT NULL",
            "SELECT a || b FROM t",

            # Aggregates
            "SELECT COUNT(*) FROM t",
            "SELECT COUNT(a) FROM t",
            "SELECT COUNT(DISTINCT a) FROM t",
            "SELECT SUM(a) FROM t",
            "SELECT AVG(a) FROM t",
            "SELECT MIN(a) FROM t",
            "SELECT MAX(a) FROM t",

            # GROUP BY / HAVING
            "SELECT a, COUNT(*) FROM t GROUP BY a",
            "SELECT a, COUNT(*) FROM t GROUP BY a HAVING COUNT(*) > 1",
            "SELECT a, b, SUM(c) FROM t GROUP BY a, b",

            # ORDER BY
            "SELECT a FROM t ORDER BY a",
            "SELECT a FROM t ORDER BY a ASC",
            "SELECT a FROM t ORDER BY a DESC",
            "SELECT a FROM t ORDER BY a, b DESC",
            "SELECT a FROM t ORDER BY 1",

            # LIMIT / OFFSET
            "SELECT a FROM t LIMIT 10",
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

            # UPDATE
            "UPDATE t SET a = 1",
            "UPDATE t SET a = 1, b = 2",
            "UPDATE t SET a = 1 WHERE b = 2",

            # DELETE
            "DELETE FROM t",
            "DELETE FROM t WHERE a = 1",

            # CREATE TABLE
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

            # DROP TABLE
            "DROP TABLE t",
            "DROP TABLE IF EXISTS t",

            # CREATE / DROP Index
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

            # Functions
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

            # Window functions
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
            "SELECT 1 + 2 * 3",
            "SELECT (1 + 2) * 3",
            "SELECT a FROM t WHERE a LIKE 'test' ESCAPE '\\'",

            # CREATE VIEW
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

            # Misc
            "SELECT a FROM t WHERE a SIMILAR TO '%pattern%'",
            "SELECT a FROM t FOR UPDATE",
            "SELECT a FROM t FOR SHARE",
            "SELECT a FROM t WHERE a::INT > 0",
            "SELECT a FROM t TABLESAMPLE BERNOULLI(10)",
            "SELECT ARRAY[1, 2, 3]",
            "SELECT a[1] FROM t",
        ]

        return stmts
