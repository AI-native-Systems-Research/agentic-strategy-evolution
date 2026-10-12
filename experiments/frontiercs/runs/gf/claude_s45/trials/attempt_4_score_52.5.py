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
        ]
