class Solution:
    def solve(self, resources_path: str) -> list[str]:
        """Generate SQL test cases to maximize parser coverage."""

        # Comprehensive set of SQL statements covering various features
        test_cases = [
            # Basic SELECT statements
            "SELECT * FROM users",
            "SELECT id, name FROM products",
            "SELECT DISTINCT category FROM items",
            "SELECT ALL status FROM orders",
            "SELECT TOP 10 * FROM logs",

            # WHERE clauses with various operators
            "SELECT * FROM users WHERE age > 18",
            "SELECT * FROM users WHERE name = 'John'",
            "SELECT * FROM users WHERE active IS NULL",
            "SELECT * FROM users WHERE id IN (1, 2, 3)",
            "SELECT * FROM users WHERE age BETWEEN 18 AND 65",
            "SELECT * FROM users WHERE name LIKE '%Smith%'",
            "SELECT * FROM users WHERE name NOT LIKE 'A%'",
            "SELECT * FROM users WHERE age NOT BETWEEN 10 AND 20",
            "SELECT * FROM users WHERE id NOT IN (1, 2)",

            # Logical operators
            "SELECT * FROM users WHERE age > 18 AND active = 1",
            "SELECT * FROM users WHERE role = 'admin' OR role = 'moderator'",
            "SELECT * FROM users WHERE NOT deleted",
            "SELECT * FROM users WHERE age > 18 AND (status = 'active' OR status = 'trial')",

            # ORDER BY
            "SELECT * FROM users ORDER BY created_at",
            "SELECT * FROM users ORDER BY name ASC, age DESC",
            "SELECT * FROM users ORDER BY name ASC NULLS FIRST",
            "SELECT * FROM users ORDER BY name DESC NULLS LAST",

            # GROUP BY and HAVING
            "SELECT category, COUNT(*) FROM products GROUP BY category",
            "SELECT category, COUNT(*) FROM products GROUP BY category HAVING COUNT(*) > 5",
            "SELECT category, AVG(price) FROM products GROUP BY category HAVING AVG(price) > 100",

            # Aggregate functions
            "SELECT COUNT(*) FROM users",
            "SELECT AVG(price) FROM products",
            "SELECT SUM(quantity) FROM orders",
            "SELECT MIN(price), MAX(price) FROM products",
            "SELECT COUNT(DISTINCT category) FROM items",
            "SELECT STDDEV(price) FROM products",
            "SELECT VARIANCE(age) FROM users",

            # JOINs
            "SELECT * FROM users JOIN orders ON users.id = orders.user_id",
            "SELECT * FROM users LEFT JOIN orders ON users.id = orders.user_id",
            "SELECT * FROM users RIGHT JOIN orders ON users.id = orders.user_id",
            "SELECT * FROM users INNER JOIN orders ON users.id = orders.user_id",
            "SELECT * FROM users OUTER JOIN orders ON users.id = orders.user_id",
            "SELECT * FROM users FULL OUTER JOIN orders ON users.id = orders.user_id",
            "SELECT * FROM a JOIN b ON a.id = b.a_id JOIN c ON b.id = c.b_id",
            "SELECT * FROM users LEFT OUTER JOIN orders ON users.id = orders.user_id",
            "SELECT * FROM users RIGHT OUTER JOIN orders ON users.id = orders.user_id",
            "SELECT * FROM users NATURAL JOIN profiles",

            # Subqueries
            "SELECT * FROM users WHERE id IN (SELECT user_id FROM orders)",
            "SELECT * FROM products WHERE price > (SELECT AVG(price) FROM products)",
            "SELECT * FROM (SELECT * FROM users WHERE active = 1) AS active_users",
            "SELECT * FROM users WHERE id = (SELECT MAX(id) FROM users)",
            "SELECT *, (SELECT COUNT(*) FROM orders WHERE orders.user_id = users.id) AS order_count FROM users",

            # INSERT statements
            "INSERT INTO users (name, email) VALUES ('John', 'john@example.com')",
            "INSERT INTO users VALUES (1, 'John', 'john@example.com')",
            "INSERT INTO users (name, email) VALUES ('John', 'john@example.com'), ('Jane', 'jane@example.com')",
            "INSERT INTO users SELECT * FROM temp_users",
            "INSERT INTO users (name) SELECT name FROM old_users WHERE active = 1",

            # UPDATE statements
            "UPDATE users SET active = 1",
            "UPDATE users SET active = 1 WHERE id = 5",
            "UPDATE users SET name = 'John', email = 'john@example.com' WHERE id = 1",
            "UPDATE users SET counter = counter + 1 WHERE id = 5",

            # DELETE statements
            "DELETE FROM users",
            "DELETE FROM users WHERE id = 5",
            "DELETE FROM users WHERE active = 0 AND created_at < '2020-01-01'",

            # CREATE TABLE
            "CREATE TABLE users (id INT, name VARCHAR(100))",
            "CREATE TABLE products (id INT PRIMARY KEY, name VARCHAR(100), price DECIMAL(10, 2))",
            "CREATE TABLE IF NOT EXISTS logs (id INT, message TEXT)",
            "CREATE TABLE orders (id INT NOT NULL, user_id INT, total DECIMAL(10,2) DEFAULT 0)",
            "CREATE TABLE temp_data (id INT, data TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)",

            # DROP TABLE
            "DROP TABLE users",
            "DROP TABLE IF EXISTS users",

            # ALTER TABLE
            "ALTER TABLE users ADD COLUMN age INT",
            "ALTER TABLE users DROP COLUMN age",
            "ALTER TABLE users RENAME TO customers",
            "ALTER TABLE users MODIFY COLUMN name VARCHAR(200)",

            # TRUNCATE
            "TRUNCATE TABLE logs",

            # LIMIT and OFFSET
            "SELECT * FROM users LIMIT 10",
            "SELECT * FROM users LIMIT 10 OFFSET 20",
            "SELECT * FROM users OFFSET 10",

            # Complex expressions
            "SELECT id * 2 AS doubled FROM numbers",
            "SELECT price * quantity AS total FROM order_items",
            "SELECT CONCAT(first_name, ' ', last_name) AS full_name FROM users",
            "SELECT COALESCE(phone, email, 'no contact') FROM users",
            "SELECT NULLIF(value, 0) FROM measurements",

            # CASE statements
            "SELECT CASE WHEN age < 18 THEN 'minor' ELSE 'adult' END FROM users",
            "SELECT CASE status WHEN 'active' THEN 1 WHEN 'inactive' THEN 0 ELSE -1 END FROM accounts",
            "SELECT CASE WHEN score >= 90 THEN 'A' WHEN score >= 80 THEN 'B' ELSE 'C' END FROM grades",

            # EXISTS
            "SELECT * FROM users WHERE EXISTS (SELECT 1 FROM orders WHERE orders.user_id = users.id)",
            "SELECT * FROM users WHERE NOT EXISTS (SELECT 1 FROM orders WHERE orders.user_id = users.id)",

            # UNION
            "SELECT name FROM users UNION SELECT name FROM admins",
            "SELECT id FROM products UNION ALL SELECT id FROM archived_products",
            "SELECT name FROM users INTERSECT SELECT name FROM employees",
            "SELECT name FROM all_users EXCEPT SELECT name FROM blocked_users",

            # Multiple conditions
            "SELECT * FROM orders WHERE status = 'shipped' AND total > 100 OR priority = 'high'",

            # Nested functions
            "SELECT UPPER(TRIM(name)) FROM users",
            "SELECT ROUND(AVG(price), 2) FROM products",
            "SELECT ABS(balance) FROM accounts",

            # NULL checks
            "SELECT * FROM users WHERE email IS NOT NULL",

            # String literals with escaping
            "SELECT * FROM users WHERE name = 'O''Brien'",

            # Numeric expressions
            "SELECT * FROM products WHERE price > 10.5 AND price < 100.99",
            "SELECT * FROM items WHERE quantity >= 0",
            "SELECT * FROM products WHERE price BETWEEN 10 AND 100",

            # Date/time
            "SELECT * FROM events WHERE event_date > '2024-01-01'",
            "SELECT NOW() AS current_time",
            "SELECT CURRENT_DATE AS today",
            "SELECT CURRENT_TIMESTAMP AS now",

            # Wildcard with table prefix
            "SELECT users.* FROM users JOIN orders ON users.id = orders.user_id",

            # Multiple JOINs with WHERE
            "SELECT * FROM users u JOIN orders o ON u.id = o.user_id WHERE u.active = 1",

            # Complex GROUP BY
            "SELECT region, category, SUM(sales) FROM transactions GROUP BY region, category",
            "SELECT YEAR(order_date), MONTH(order_date), COUNT(*) FROM orders GROUP BY YEAR(order_date), MONTH(order_date)",

            # Arithmetic in SELECT
            "SELECT price + tax AS total_price FROM products",
            "SELECT quantity - shipped AS remaining FROM inventory",
            "SELECT price / 2 AS half_price FROM products",
            "SELECT price % 10 AS remainder FROM products",

            # IN with subquery
            "SELECT * FROM customers WHERE country IN (SELECT country FROM offices)",

            # Multiple aggregate functions
            "SELECT COUNT(*), AVG(salary), MIN(age), MAX(experience) FROM employees",

            # Complex WHERE with parentheses
            "SELECT * FROM users WHERE (status = 'active' OR status = 'pending') AND age > 18",

            # Comparison operators
            "SELECT * FROM products WHERE price <> 0",
            "SELECT * FROM items WHERE stock <= 10",
            "SELECT * FROM products WHERE price != 0",

            # ORDER BY with expression
            "SELECT * FROM products ORDER BY price * quantity DESC",

            # String functions
            "SELECT LENGTH(name) FROM users",
            "SELECT SUBSTRING(description, 1, 100) FROM articles",
            "SELECT LOWER(name) FROM users",
            "SELECT UPPER(status) FROM orders",
            "SELECT TRIM(name) FROM users",
            "SELECT LTRIM(name) FROM users",
            "SELECT RTRIM(name) FROM users",

            # Cross join
            "SELECT * FROM table1 CROSS JOIN table2",

            # Aliasing
            "SELECT u.name, o.total FROM users u, orders o WHERE u.id = o.user_id",

            # Column arithmetic
            "SELECT (price * 1.1) AS price_with_tax FROM products",

            # WITH clause (CTE)
            "WITH active_users AS (SELECT * FROM users WHERE active = 1) SELECT * FROM active_users",
            "WITH totals AS (SELECT user_id, SUM(amount) AS total FROM orders GROUP BY user_id) SELECT users.name, totals.total FROM users JOIN totals ON users.id = totals.user_id",

            # Window functions
            "SELECT name, salary, ROW_NUMBER() OVER (ORDER BY salary DESC) FROM employees",
            "SELECT name, salary, RANK() OVER (PARTITION BY department ORDER BY salary DESC) FROM employees",
            "SELECT name, AVG(salary) OVER (PARTITION BY department) FROM employees",

            # ANY and ALL
            "SELECT * FROM products WHERE price > ANY (SELECT price FROM discounted_products)",
            "SELECT * FROM products WHERE price > ALL (SELECT price FROM budget_items)",

            # Boolean literals
            "SELECT * FROM users WHERE active = TRUE",
            "SELECT * FROM users WHERE deleted = FALSE",

            # Multiple SELECT columns
            "SELECT id, name, email, status, created_at FROM users",

            # Casting
            "SELECT CAST(price AS INT) FROM products",
            "SELECT CONVERT(VARCHAR, order_date, 101) FROM orders",

            # Date functions
            "SELECT DATE_ADD(created_at, INTERVAL 7 DAY) FROM users",
            "SELECT DATE_SUB(NOW(), INTERVAL 1 MONTH) AS last_month",
            "SELECT DATEDIFF(end_date, start_date) FROM projects",

            # Mathematical functions
            "SELECT SQRT(value) FROM measurements",
            "SELECT POWER(base, exponent) FROM calculations",
            "SELECT CEIL(price) FROM products",
            "SELECT FLOOR(price) FROM products",

            # HAVING without GROUP BY
            "SELECT * FROM users HAVING COUNT(*) > 0",

            # Multiple WHERE conditions
            "SELECT * FROM orders WHERE status = 'pending' AND total > 100 AND user_id IN (SELECT id FROM premium_users)",

            # Nested CASE
            "SELECT CASE WHEN age < 18 THEN 'minor' WHEN age < 65 THEN CASE WHEN employed THEN 'working adult' ELSE 'unemployed adult' END ELSE 'senior' END FROM people",

            # Complex JOIN conditions
            "SELECT * FROM orders o JOIN users u ON o.user_id = u.id AND u.status = 'active' AND o.total > 100",

            # Multiple ORDER BY expressions
            "SELECT * FROM products ORDER BY category ASC, price DESC, name ASC",

            # Subquery in SELECT
            "SELECT name, (SELECT COUNT(*) FROM orders WHERE orders.user_id = users.id) FROM users",

            # Multiple GROUP BY columns
            "SELECT country, city, status, COUNT(*) FROM users GROUP BY country, city, status",
        ]

        return test_cases
