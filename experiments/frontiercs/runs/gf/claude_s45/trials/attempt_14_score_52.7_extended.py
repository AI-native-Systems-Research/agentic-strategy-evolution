class Solution:
    def solve(self, resources_path: str) -> list[str]:
        """Generate SQL test cases to maximize parser coverage."""

        # Focused test cases targeting maximum coverage with minimal redundancy
        return [
            # Core SELECT variations
            "SELECT * FROM users",
            "SELECT DISTINCT id, name FROM products",
            "SELECT TOP 10 * FROM logs",

            # WHERE with diverse operators
            "SELECT * FROM users WHERE age > 18 AND active = 1",
            "SELECT * FROM users WHERE name LIKE '%Smith%'",
            "SELECT * FROM users WHERE id IN (1, 2, 3)",
            "SELECT * FROM users WHERE age BETWEEN 18 AND 65",
            "SELECT * FROM users WHERE email IS NULL",
            "SELECT * FROM users WHERE NOT deleted",
            "SELECT * FROM users WHERE (status = 'active' OR status = 'trial') AND age > 18",

            # Aggregates and GROUP BY
            "SELECT category, COUNT(*), AVG(price), MIN(price), MAX(price) FROM products GROUP BY category",
            "SELECT category FROM products GROUP BY category HAVING COUNT(*) > 5",
            "SELECT COUNT(DISTINCT user_id) FROM orders",

            # ORDER BY variations
            "SELECT * FROM users ORDER BY name ASC, age DESC",
            "SELECT * FROM users ORDER BY created_at DESC NULLS LAST",

            # All JOIN types
            "SELECT * FROM users u JOIN orders o ON u.id = o.user_id",
            "SELECT * FROM users LEFT JOIN orders ON users.id = orders.user_id",
            "SELECT * FROM users RIGHT JOIN orders ON users.id = orders.user_id",
            "SELECT * FROM users FULL OUTER JOIN orders ON users.id = orders.user_id",
            "SELECT * FROM users NATURAL JOIN profiles",
            "SELECT * FROM table1 CROSS JOIN table2",
            "SELECT * FROM a JOIN b ON a.id = b.a_id JOIN c ON b.id = c.b_id",

            # Subqueries in different positions
            "SELECT * FROM users WHERE id IN (SELECT user_id FROM orders)",
            "SELECT * FROM products WHERE price > (SELECT AVG(price) FROM products)",
            "SELECT * FROM (SELECT * FROM users WHERE active = 1) AS active_users",
            "SELECT id, (SELECT COUNT(*) FROM orders WHERE user_id = users.id) FROM users",
            "SELECT * FROM products p WHERE price > (SELECT AVG(price) FROM products WHERE category = p.category)",

            # INSERT variations
            "INSERT INTO users (name, email) VALUES ('John', 'john@example.com')",
            "INSERT INTO users VALUES (1, 'John', 'john@example.com')",
            "INSERT INTO users (name, email) VALUES ('John', 'j@a.com'), ('Jane', 'jane@a.com')",
            "INSERT INTO archive SELECT * FROM users WHERE active = 0",

            # UPDATE variations
            "UPDATE users SET active = 1",
            "UPDATE users SET active = 1 WHERE id = 5",
            "UPDATE users SET name = 'John', email = 'john@a.com' WHERE id = 1",
            "UPDATE products SET price = price * 1.1 WHERE category = 'electronics'",

            # DELETE variations
            "DELETE FROM users",
            "DELETE FROM users WHERE id = 5",

            # DDL statements
            "CREATE TABLE users (id INT PRIMARY KEY, name VARCHAR(100), age INT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS logs (id INT, message TEXT)",
            "CREATE INDEX idx_email ON users(email)",
            "CREATE UNIQUE INDEX idx_sku ON products(sku)",
            "DROP TABLE users",
            "DROP TABLE IF EXISTS temp_data",
            "DROP INDEX idx_email",
            "ALTER TABLE users ADD COLUMN age INT",
            "ALTER TABLE users DROP COLUMN age",
            "TRUNCATE TABLE logs",

            # CASE expressions
            "SELECT CASE WHEN age < 18 THEN 'minor' ELSE 'adult' END FROM users",
            "SELECT CASE status WHEN 'active' THEN 1 WHEN 'inactive' THEN 0 ELSE -1 END FROM accounts",

            # EXISTS and NOT EXISTS
            "SELECT * FROM users WHERE EXISTS (SELECT 1 FROM orders WHERE orders.user_id = users.id)",
            "SELECT * FROM users WHERE NOT EXISTS (SELECT 1 FROM orders WHERE orders.user_id = users.id)",

            # Set operations
            "SELECT name FROM users UNION SELECT name FROM admins",
            "SELECT id FROM products UNION ALL SELECT id FROM archived_products",
            "SELECT name FROM users INTERSECT SELECT name FROM employees",
            "SELECT name FROM all_users EXCEPT SELECT name FROM blocked_users",

            # Functions
            "SELECT UPPER(name), LOWER(email), TRIM(status) FROM users",
            "SELECT CONCAT(first_name, ' ', last_name) FROM users",
            "SELECT COALESCE(phone, email, 'no contact') FROM users",
            "SELECT LENGTH(name), SUBSTRING(description, 1, 100) FROM products",
            "SELECT ABS(balance), ROUND(price, 2), SQRT(area) FROM data",
            "SELECT NOW(), CURRENT_DATE, CURRENT_TIMESTAMP",

            # CTEs
            "WITH active_users AS (SELECT * FROM users WHERE active = 1) SELECT * FROM active_users",
            "WITH cte1 AS (SELECT * FROM users WHERE active = 1), cte2 AS (SELECT * FROM orders WHERE total > 100) SELECT * FROM cte1 JOIN cte2 ON cte1.id = cte2.user_id",

            # Window functions
            "SELECT name, salary, ROW_NUMBER() OVER (ORDER BY salary DESC) FROM employees",
            "SELECT name, AVG(salary) OVER (PARTITION BY department ORDER BY hire_date) FROM employees",

            # Limit and offset
            "SELECT * FROM users LIMIT 10",
            "SELECT * FROM users LIMIT 10 OFFSET 20",

            # Complex expressions
            "SELECT (price * quantity * (1 + tax_rate / 100)) AS total FROM items",
            "SELECT price + tax, quantity - shipped, price / 2, price % 10 FROM data",

            # ANY and ALL
            "SELECT * FROM products WHERE price > ANY (SELECT price FROM discounted)",
            "SELECT * FROM products WHERE price > ALL (SELECT price FROM budget)",

            # Boolean literals
            "SELECT * FROM users WHERE active = TRUE AND deleted = FALSE",

            # Complex multi-table
            "SELECT * FROM users u, orders o WHERE u.id = o.user_id",

            # Nested subqueries
            "SELECT * FROM users WHERE id IN (SELECT user_id FROM orders WHERE product_id IN (SELECT id FROM products WHERE category = 'electronics'))",

            # Self-join
            "SELECT a.name, b.name FROM employees a JOIN employees b ON a.manager_id = b.id",

            # Advanced DDL
            "CREATE TABLE orders (id INT PRIMARY KEY, user_id INT NOT NULL, total DECIMAL(10,2) CHECK (total >= 0), FOREIGN KEY (user_id) REFERENCES users(id))",
            "CREATE VIEW active_users AS SELECT * FROM users WHERE active = 1",
            "DROP VIEW active_users",

            # Transaction control
            "BEGIN TRANSACTION",
            "COMMIT",
            "ROLLBACK",

            # Casting
            "SELECT CAST(price AS INT) FROM products",

            # String patterns
            "SELECT * FROM users WHERE email LIKE '%@gmail.com' OR name LIKE 'A%'",

            # Date arithmetic
            "SELECT * FROM events WHERE event_date >= CURRENT_DATE - INTERVAL '7 days'",

            # Edge cases
            "SELECT * FROM accounts WHERE balance < -100",
            "SELECT * FROM users WHERE name = 'O''Brien'",
            "SELECT first_name || ' ' || last_name FROM users",

            # Additional coverage targets
            "SELECT ALL * FROM users",
            "SELECT * FROM users WHERE id NOT IN (1, 2)",
            "SELECT * FROM users WHERE age NOT BETWEEN 10 AND 20",
            "SELECT * FROM users WHERE name NOT LIKE 'A%'",
            "SELECT * FROM products ORDER BY price ASC NULLS FIRST",
            "SELECT * FROM users OFFSET 10",
            "SELECT COUNT(*) OVER () FROM users",
            "SELECT RANK() OVER (PARTITION BY dept ORDER BY salary) FROM emp",
            "SELECT NULLIF(value, 0) FROM measurements",
            "SELECT * FROM users FETCH FIRST 5 ROWS ONLY",
            "INSERT INTO logs DEFAULT VALUES",
            "UPDATE products SET price = (SELECT AVG(price) FROM products)",
            "EXPLAIN SELECT * FROM users",
            "SELECT POWER(2, 3), CEIL(3.5), FLOOR(3.5) FROM dual",
            "SELECT DATE_ADD(NOW(), INTERVAL 1 DAY)",
            "SELECT DATEDIFF(end_date, start_date) FROM projects",
            "WITH RECURSIVE nums AS (SELECT 1 AS n UNION ALL SELECT n+1 FROM nums WHERE n<5) SELECT * FROM nums",
            "SELECT category FROM products GROUP BY category HAVING AVG(price) > 50",
            "SELECT * FROM orders WHERE total > 100 OR (status = 'pending' AND priority = 'high')",
            "SELECT * FROM users u JOIN orders o ON u.id = o.user_id AND u.status = 'active'",
            "SELECT CASE WHEN x > 0 THEN 'pos' WHEN x < 0 THEN 'neg' ELSE 'zero' END FROM data",
            "SELECT name FROM users UNION SELECT name FROM admins ORDER BY name",
            "SELECT DISTINCT ON (category) * FROM products",
            "SELECT * FROM users FOR UPDATE",
            "SELECT * FROM users WHERE active IS TRUE",
            "SELECT * FROM users WHERE deleted IS NOT TRUE",
            "SELECT VARIANCE(salary), STDDEV(salary) FROM employees",
            "SELECT * FROM products WHERE price > 1.5e10",
            "SELECT * FROM users WHERE id = ANY (SELECT user_id FROM orders)",
            "SELECT CONVERT(VARCHAR, date_col, 101) FROM events",
            "SELECT LTRIM(name), RTRIM(name) FROM users",
            "SELECT * FROM products WHERE name LIKE '%\\_%' ESCAPE '\\'",
            "SELECT category, region, SUM(sales) FROM trans GROUP BY ROLLUP(category, region)",
            "SELECT category, region, SUM(sales) FROM trans GROUP BY CUBE(category, region)",
            "DELETE u FROM users u JOIN banned b ON u.email = b.email",
            "ALTER TABLE users RENAME TO customers",
            "ALTER TABLE users MODIFY COLUMN name VARCHAR(200)",
            "SELECT * FROM users LEFT OUTER JOIN orders ON users.id = orders.user_id",
            "SELECT * FROM users RIGHT OUTER JOIN orders ON users.id = orders.user_id",
            "SELECT * FROM users OUTER JOIN orders ON users.id = orders.user_id",
            "SELECT id, name, price FROM products WHERE stock > 0",
            "SELECT * FROM (SELECT * FROM users WHERE active = 1) u JOIN orders o ON u.id = o.user_id",
            "SELECT COUNT(*), SUM(total), AVG(total) FROM orders WHERE status = 'completed'",
            "SELECT * FROM users WHERE age > 18 AND (country = 'US' OR country = 'CA') AND verified = 1",

            # Tokenizer and literal edge cases
            "SELECT 0.0",
            "SELECT .5",
            "SELECT 5.",
            "SELECT 1E0",
            "SELECT 1e+5",
            "SELECT 1e-5",
            "SELECT DATE '2024-01-01'",
            "SELECT TIME '12:30:45'",
            "SELECT TIMESTAMP '2024-01-01 12:30:45'",
            "SELECT INTERVAL '1' DAY",

            # Operators not yet fully tested
            "SELECT a DIV b FROM t",
            "SELECT a MOD b FROM t",
            "SELECT a XOR b FROM t",

            # Window frame specifications
            "SELECT SUM(a) OVER (ORDER BY b ROWS BETWEEN 1 PRECEDING AND 1 FOLLOWING) FROM t",
            "SELECT AVG(a) OVER (ORDER BY b RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) FROM t",
            "SELECT COUNT(*) OVER (ORDER BY a ROWS UNBOUNDED PRECEDING) FROM t",
            "SELECT SUM(a) OVER (ORDER BY b ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) FROM t",

            # Additional JOIN syntax
            "SELECT * FROM t1 JOIN t2 USING (id)",

            # Set operations with parentheses
            "(SELECT a FROM t1) UNION (SELECT a FROM t2)",
            "(SELECT a FROM t1 UNION SELECT a FROM t2) UNION SELECT a FROM t3",

            # Complex IN clauses
            "SELECT * FROM t WHERE (a, b) IN (SELECT c, d FROM t2)",
            "SELECT * FROM t WHERE a IN (1)",

            # Aggregate modifiers
            "SELECT COUNT(ALL a) FROM t",
            "SELECT SUM(ALL a) FROM t",
            "SELECT SUM(DISTINCT a), AVG(DISTINCT b) FROM t",

            # Multiple CTEs with dependencies
            "WITH a AS (SELECT 1 AS x), b AS (SELECT x FROM a) SELECT * FROM b",

            # Complex expressions in different clauses
            "SELECT * FROM t WHERE CASE WHEN a > 0 THEN b ELSE c END = 1",
            "SELECT * FROM t GROUP BY CASE WHEN a > 0 THEN 1 ELSE 0 END",
            "SELECT * FROM t ORDER BY CASE WHEN a IS NULL THEN 1 ELSE 0 END, a",

            # HAVING without aggregate in condition
            "SELECT a, COUNT(*) FROM t GROUP BY a HAVING a > 0",

            # ORDER BY position numbers
            "SELECT a, b, c FROM t ORDER BY 1, 2, 3",

            # Multiple levels of nesting
            "SELECT * FROM (SELECT * FROM (SELECT * FROM t) AS s1) AS s2",

            # Complex BETWEEN
            "SELECT * FROM t WHERE a + b BETWEEN c AND d",

            # LIKE patterns
            "SELECT * FROM t WHERE a LIKE 'a%b%c'",
            "SELECT * FROM t WHERE a LIKE '_a_'",

            # Self-join with aliases
            "SELECT * FROM t AS t1, t AS t2 WHERE t1.id = t2.parent_id",

            # Multiple window functions
            "SELECT ROW_NUMBER() OVER (ORDER BY a), RANK() OVER (ORDER BY b), SUM(c) OVER (ORDER BY d) FROM t",

            # Qualified column names
            "SELECT t.a, t.b, t.c FROM t",

            # UNION DISTINCT
            "SELECT a FROM t1 UNION DISTINCT SELECT a FROM t2",

            # Complex DELETE
            "DELETE FROM t WHERE a = 1 AND b = 2 OR c > 3",

            # UPDATE with multiple subqueries
            "UPDATE t SET a = (SELECT MAX(x) FROM t2), b = (SELECT MIN(y) FROM t3)",

            # INSERT with reordered columns
            "INSERT INTO t (b, a) VALUES (2, 1)",

            # CROSS JOIN with condition
            "SELECT * FROM t1 CROSS JOIN t2 WHERE t1.a = t2.a",

            # Boolean literals in expressions
            "SELECT TRUE, FALSE, NOT TRUE, NOT FALSE",

            # NULL in expressions
            "SELECT NULL, NULL + 1, NULL * 2",
        ]
