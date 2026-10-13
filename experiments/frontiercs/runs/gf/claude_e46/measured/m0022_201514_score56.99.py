import os
import re
import random

class Solution:
    def solve(self, resources_path: str) -> list[str]:
        grammar_path = os.path.join(resources_path, "sql_grammar.txt")
        parser_path = os.path.join(resources_path, "sql_engine", "parser.py")
        tokenizer_path = os.path.join(resources_path, "sql_engine", "tokenizer.py")

        grammar_src = self._read(grammar_path)
        parser_src = self._read(parser_path)
        tokenizer_src = self._read(tokenizer_path)

        # Parse grammar
        rules = self._parse_grammar(grammar_src)

        if rules:
            # Generate from grammar
            generated = self._generate_from_grammar(rules)
            # Also include hand-crafted for safety
            hand = self._hand_crafted()
            # Combine, deduplicate
            seen = set()
            result = []
            for s in generated + hand:
                s = s.strip()
                if s and s not in seen:
                    seen.add(s)
                    result.append(s)
            return result
        else:
            return self._hand_crafted()

    def _read(self, path):
        try:
            with open(path) as f:
                return f.read()
        except Exception:
            return ""

    def _parse_grammar(self, src):
        if not src.strip():
            return {}

        rules = {}
        current_rule = None

        for line in src.split('\n'):
            stripped = line.rstrip()

            # Match rule definition: <rule_name> ::= ...
            m = re.match(r'\s*<([\w_-]+)>\s*::=\s*(.*)', stripped)
            if m:
                current_rule = m.group(1)
                rhs = m.group(2).strip()
                if current_rule not in rules:
                    rules[current_rule] = []
                if rhs:
                    rules[current_rule].append(rhs)
                continue

            # Match alternative: | ...
            m2 = re.match(r'\s*\|\s*(.*)', stripped)
            if m2 and current_rule:
                rhs = m2.group(1).strip()
                if rhs:
                    rules[current_rule].append(rhs)
                continue

        return rules

    def _find_top_rule(self, rules):
        """Find the top-level rule."""
        for name in ['statement', 'sql_statement', 'sql-statement', 'program', 'sql', 'query', 'start']:
            if name in rules:
                return name

        # Find rules not referenced by others
        referenced = set()
        for alts in rules.values():
            for alt in alts:
                for m in re.finditer(r'<([\w_-]+)>', alt):
                    referenced.add(m.group(1))

        unreferenced = [n for n in rules if n not in referenced]
        if unreferenced:
            return unreferenced[0]

        return list(rules.keys())[0] if rules else None

    def _generate_from_grammar(self, rules):
        """Generate SQL statements by expanding grammar rules."""
        top = self._find_top_rule(rules)
        if not top:
            return []

        stmts = []
        random.seed(42)

        # For each alternative of each rule that's either top-level or a statement type
        # generate multiple expansions
        top_alts = rules.get(top, [])

        for alt_idx, alt in enumerate(top_alts):
            for seed in range(5):
                random.seed(42 + alt_idx * 100 + seed)
                try:
                    result = self._expand(alt, rules, depth=0, max_depth=15, seed=seed)
                    if result and len(result) < 500:
                        stmts.append(result)
                except Exception:
                    pass

        # Also try to expand sub-rules that represent different statement types
        statement_rules = [n for n in rules if any(kw in n.lower() for kw in
            ['select', 'insert', 'update', 'delete', 'create', 'drop', 'alter',
             'grant', 'revoke', 'begin', 'commit', 'rollback', 'explain',
             'truncate', 'set', 'merge', 'with'])]

        for rule_name in statement_rules:
            for alt_idx, alt in enumerate(rules.get(rule_name, [])):
                for seed in range(3):
                    random.seed(42 + hash(rule_name) % 1000 + seed)
                    try:
                        result = self._expand(alt, rules, depth=0, max_depth=15, seed=seed)
                        if result and len(result) < 500:
                            stmts.append(result)
                    except Exception:
                        pass

        return stmts

    def _expand(self, pattern, rules, depth=0, max_depth=15, seed=0):
        if depth > max_depth:
            return self._terminal_fallback(pattern)

        result_parts = []
        i = 0

        while i < len(pattern):
            c = pattern[i]

            if c == '<':
                # Non-terminal reference
                j = pattern.index('>', i)
                ref = pattern[i+1:j]
                i = j + 1

                if ref in rules and rules[ref]:
                    alts = rules[ref]
                    # Pick alternative based on seed and depth
                    idx = (seed + depth) % len(alts)
                    expanded = self._expand(alts[idx], rules, depth+1, max_depth, seed)
                    result_parts.append(expanded)
                else:
                    # Terminal or undefined - use as-is
                    result_parts.append(ref)

            elif c == '[':
                # Optional content
                j = self._find_bracket_end(pattern, i, '[', ']')
                if j > i:
                    inner = pattern[i+1:j]
                    # Include based on seed
                    if (seed + depth) % 2 == 0:
                        expanded = self._expand(inner, rules, depth+1, max_depth, seed)
                        result_parts.append(expanded)
                    i = j + 1
                else:
                    i += 1

            elif c == '{':
                # Repetition
                j = self._find_bracket_end(pattern, i, '{', '}')
                if j > i:
                    inner = pattern[i+1:j]
                    # Include 1-2 repetitions
                    reps = 1 + (seed % 2)
                    for r in range(reps):
                        expanded = self._expand(inner, rules, depth+1, max_depth, seed + r)
                        result_parts.append(expanded)
                    i = j + 1
                else:
                    i += 1

            elif c in ("'", '"'):
                # Quoted literal
                j = pattern.index(c, i+1) if c in pattern[i+1:] else len(pattern)
                result_parts.append(pattern[i+1:j])
                i = j + 1

            elif c == '|':
                # Alternative separator at this level - stop here
                break

            else:
                # Regular text
                j = i
                while j < len(pattern) and pattern[j] not in '<[{|\'">':
                    j += 1
                text = pattern[i:j].strip()
                if text:
                    result_parts.append(text)
                i = j

        return ' '.join(p for p in result_parts if p)

    def _terminal_fallback(self, pattern):
        """When max depth exceeded, try to produce a terminal."""
        # Extract any quoted strings
        quoted = re.findall(r"'([^']*)'", pattern)
        if quoted:
            return quoted[0]
        # Look for capitalized words (SQL keywords)
        words = re.findall(r'\b[A-Z]+\b', pattern)
        if words:
            return ' '.join(words)
        return "1"

    def _find_bracket_end(self, s, start, open_ch, close_ch):
        depth = 0
        for i in range(start, len(s)):
            if s[i] == open_ch:
                depth += 1
            elif s[i] == close_ch:
                depth -= 1
                if depth == 0:
                    return i
        return -1

    def _hand_crafted(self):
        return [
            "SELECT 1",
            "SELECT a, b, c FROM t",
            "SELECT * FROM t",
            "SELECT DISTINCT a FROM t",
            "SELECT ALL a FROM t",
            "SELECT a AS x, b AS y FROM t AS z",
            "SELECT t.a, t.* FROM t",
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
            "SELECT a + b, a - b, a * b, a / b, a % b, -a, +a FROM t",
            "SELECT 'hello', 3.14, -3.14, 0, TRUE, FALSE, NULL",
            "SELECT a || b FROM t",
            "SELECT (1 + 2) * 3",
            "SELECT COUNT(*), COUNT(a), COUNT(DISTINCT a), SUM(a), AVG(a), MIN(a), MAX(a) FROM t",
            "SELECT a, COUNT(*) FROM t GROUP BY a HAVING COUNT(*) > 1",
            "SELECT a, b, SUM(c) FROM t GROUP BY a, b",
            "SELECT a FROM t ORDER BY a ASC, b DESC",
            "SELECT a FROM t ORDER BY 1",
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
            "INSERT INTO t DEFAULT VALUES",
            "UPDATE t SET a = 1, b = 2 WHERE c = 3",
            "DELETE FROM t WHERE a = 1",
            "DELETE FROM t",
            "CREATE TABLE t (a INT PRIMARY KEY, b VARCHAR(255) NOT NULL, c FLOAT DEFAULT 0.0, d BOOLEAN, e DATE, f TIMESTAMP, g TEXT UNIQUE)",
            "CREATE TABLE IF NOT EXISTS t (a INT)",
            "CREATE TABLE t (a INT, b INT, PRIMARY KEY (a, b))",
            "CREATE TABLE t (a INT REFERENCES other(id))",
            "CREATE TABLE t (a INT CHECK (a > 0))",
            "CREATE TABLE t (a DECIMAL(10, 2), b INTEGER, c REAL, d CHAR(10), e VARCHAR(100))",
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
            "SELECT UPPER(a), LOWER(a), LENGTH(a), TRIM(a) FROM t",
            "SELECT SUBSTRING(a FROM 1 FOR 3) FROM t",
            "SELECT SUBSTR(a, 1, 3) FROM t",
            "SELECT COALESCE(a, b, c), NULLIF(a, b) FROM t",
            "SELECT CAST(a AS INT), CAST(b AS VARCHAR(100)) FROM t",
            "SELECT ABS(a), ROUND(a, 2), CONCAT(a, b) FROM t",
            "SELECT NOW(), CURRENT_TIMESTAMP, CURRENT_DATE",
            "SELECT ROW_NUMBER() OVER (ORDER BY a), RANK() OVER (PARTITION BY b ORDER BY a), DENSE_RANK() OVER (ORDER BY a DESC) FROM t",
            "SELECT SUM(b) OVER (PARTITION BY c ORDER BY d) FROM t",
            "SELECT LAG(a, 1) OVER (ORDER BY a), LEAD(a, 1) OVER (ORDER BY a) FROM t",
            "SELECT FIRST_VALUE(a) OVER (ORDER BY a), LAST_VALUE(a) OVER (ORDER BY a) FROM t",
            "SELECT NTILE(4) OVER (ORDER BY a) FROM t",
            "SELECT SUM(b) OVER (ORDER BY a ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) FROM t",
            "SELECT SUM(b) OVER (ORDER BY a ROWS BETWEEN 1 PRECEDING AND 1 FOLLOWING) FROM t",
            "SELECT SUM(b) OVER (ORDER BY a RANGE BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) FROM t",
            "SELECT COUNT(*) OVER () FROM t",
            "WITH cte AS (SELECT a FROM t) SELECT * FROM cte",
            "WITH cte1 AS (SELECT a FROM t1), cte2 AS (SELECT b FROM t2) SELECT * FROM cte1 JOIN cte2 ON cte1.a = cte2.b",
            "WITH RECURSIVE cte AS (SELECT 1 AS n UNION ALL SELECT n + 1 FROM cte WHERE n < 10) SELECT * FROM cte",
            "SELECT DISTINCT ON (a) a, b FROM t",
            "SELECT DATE '2023-01-01'",
            "SELECT TIMESTAMP '2023-01-01 00:00:00'",
            "SELECT TIME '12:00:00'",
            "SELECT INTERVAL '1' DAY",
            "SELECT a FROM t1 WHERE a > (SELECT AVG(b) FROM t2) ORDER BY a LIMIT 5",
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
