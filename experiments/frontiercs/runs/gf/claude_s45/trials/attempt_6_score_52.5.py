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

            # Additional standard SQL coverage
            "SELECT COUNT(*) AS total FROM users WHERE active = 1",
            "SELECT * FROM users WHERE status IN ('active', 'trial', 'premium')",
            "SELECT SUM(price * quantity) FROM order_items",
            "SELECT * FROM products WHERE description IS NOT NULL AND stock > 0",
            "SELECT user_id, product_id, COUNT(*) FROM purchases GROUP BY user_id, product_id",
            "SELECT * FROM users WHERE email LIKE '%@%.%'",
            "SELECT * FROM logs WHERE level = 'ERROR' OR level = 'CRITICAL'",
            "SELECT YEAR(created_at) AS year, COUNT(*) FROM orders GROUP BY YEAR(created_at)",
            "SELECT * FROM users WHERE last_login < DATE_SUB(NOW(), INTERVAL 90 DAY)",
            "SELECT AVG(age) AS avg_age, MIN(age) AS min_age, MAX(age) AS max_age FROM users GROUP BY country",
            "SELECT * FROM products WHERE price BETWEEN 10.0 AND 100.0 AND category = 'electronics'",
            "SELECT u.name, COUNT(o.id) AS order_count FROM users u LEFT JOIN orders o ON u.id = o.user_id GROUP BY u.name",
            "SELECT * FROM orders WHERE created_at >= '2024-01-01' AND created_at < '2025-01-01'",
            "SELECT DISTINCT category, brand FROM products WHERE active = 1",
            "SELECT * FROM users WHERE (age BETWEEN 25 AND 35) OR (age BETWEEN 45 AND 55)",
            "SELECT product_id, SUM(quantity) AS total_quantity FROM inventory GROUP BY product_id HAVING SUM(quantity) > 100",
            "SELECT * FROM events WHERE event_type IN (SELECT type FROM active_event_types)",
            "SELECT CONCAT(street, ', ', city, ', ', state) AS address FROM locations",
            "SELECT * FROM transactions WHERE amount > 1000 AND status = 'completed' ORDER BY amount DESC LIMIT 10",
            "SELECT user_id, MAX(order_date) AS last_order FROM orders GROUP BY user_id",
            "INSERT INTO audit_log (user_id, action, timestamp) VALUES (1, 'login', NOW())",
            "UPDATE inventory SET quantity = quantity - 5 WHERE product_id = 123",
            "DELETE FROM sessions WHERE last_activity < DATE_SUB(NOW(), INTERVAL 24 HOUR)",
            "SELECT * FROM products p1 WHERE NOT EXISTS (SELECT 1 FROM orders o WHERE o.product_id = p1.id)",
            "SELECT region, SUM(sales) AS total_sales FROM transactions GROUP BY region ORDER BY total_sales DESC",
            "SELECT * FROM users WHERE UPPER(name) = 'JOHN DOE'",
            "SELECT REPLACE(phone, '-', '') AS clean_phone FROM contacts",
            "SELECT * FROM products WHERE price > (SELECT AVG(price) * 1.5 FROM products)",
            "SELECT DATE_FORMAT(order_date, '%Y-%m') AS month, COUNT(*) FROM orders GROUP BY DATE_FORMAT(order_date, '%Y-%m')",
            "SELECT * FROM users u1 JOIN users u2 ON u1.referrer_id = u2.id",
            "SELECT IF(stock > 0, 'In Stock', 'Out of Stock') AS availability FROM products",
            "SELECT * FROM orders WHERE MONTH(order_date) = 12 AND YEAR(order_date) = 2024",
            "SELECT category, AVG(rating) AS avg_rating FROM products WHERE rating IS NOT NULL GROUP BY category",
            "SELECT * FROM logs WHERE message LIKE '%error%' OR message LIKE '%exception%'",
            "SELECT FLOOR(price / 10) * 10 AS price_range, COUNT(*) FROM products GROUP BY FLOOR(price / 10)",
            "SELECT * FROM users WHERE created_at BETWEEN '2024-01-01' AND '2024-12-31'",
            "SELECT employee_id, first_name, last_name, CONCAT(first_name, ' ', last_name) AS full_name FROM employees",
            "SELECT * FROM products WHERE (category = 'books' AND price < 20) OR (category = 'electronics' AND price < 100)",
            "SELECT DISTINCT user_id FROM orders WHERE order_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)",
            "SELECT COUNT(CASE WHEN status = 'active' THEN 1 END) AS active_count FROM users",
            "SELECT * FROM orders o1 WHERE total > (SELECT AVG(total) FROM orders o2 WHERE o2.user_id = o1.user_id)",
        ]
