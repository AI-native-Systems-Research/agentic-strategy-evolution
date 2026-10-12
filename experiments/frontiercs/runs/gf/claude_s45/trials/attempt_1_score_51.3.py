class Solution:
    def solve(self, resources_path: str) -> list[str]:
        """Generate SQL test cases to maximize parser coverage."""

        # Comprehensive set of SQL statements covering various features
        test_cases = [
            # Basic SELECT statements
            "SELECT * FROM users",
            "SELECT id, name FROM products",
            "SELECT DISTINCT category FROM items",

            # WHERE clauses with various operators
            "SELECT * FROM users WHERE age > 18",
            "SELECT * FROM users WHERE name = 'John'",
            "SELECT * FROM users WHERE active IS NULL",
            "SELECT * FROM users WHERE id IN (1, 2, 3)",
            "SELECT * FROM users WHERE age BETWEEN 18 AND 65",
            "SELECT * FROM users WHERE name LIKE '%Smith%'",

            # Logical operators
            "SELECT * FROM users WHERE age > 18 AND active = 1",
            "SELECT * FROM users WHERE role = 'admin' OR role = 'moderator'",
            "SELECT * FROM users WHERE NOT deleted",

            # ORDER BY
            "SELECT * FROM users ORDER BY created_at",
            "SELECT * FROM users ORDER BY name ASC, age DESC",

            # GROUP BY and HAVING
            "SELECT category, COUNT(*) FROM products GROUP BY category",
            "SELECT category, COUNT(*) FROM products GROUP BY category HAVING COUNT(*) > 5",

            # Aggregate functions
            "SELECT COUNT(*) FROM users",
            "SELECT AVG(price) FROM products",
            "SELECT SUM(quantity) FROM orders",
            "SELECT MIN(price), MAX(price) FROM products",

            # JOINs
            "SELECT * FROM users JOIN orders ON users.id = orders.user_id",
            "SELECT * FROM users LEFT JOIN orders ON users.id = orders.user_id",
            "SELECT * FROM users RIGHT JOIN orders ON users.id = orders.user_id",
            "SELECT * FROM users INNER JOIN orders ON users.id = orders.user_id",
            "SELECT * FROM a JOIN b ON a.id = b.a_id JOIN c ON b.id = c.b_id",

            # Subqueries
            "SELECT * FROM users WHERE id IN (SELECT user_id FROM orders)",
            "SELECT * FROM products WHERE price > (SELECT AVG(price) FROM products)",
            "SELECT * FROM (SELECT * FROM users WHERE active = 1) AS active_users",

            # INSERT statements
            "INSERT INTO users (name, email) VALUES ('John', 'john@example.com')",
            "INSERT INTO users VALUES (1, 'John', 'john@example.com')",
            "INSERT INTO users (name, email) VALUES ('John', 'john@example.com'), ('Jane', 'jane@example.com')",

            # UPDATE statements
            "UPDATE users SET active = 1",
            "UPDATE users SET active = 1 WHERE id = 5",
            "UPDATE users SET name = 'John', email = 'john@example.com' WHERE id = 1",

            # DELETE statements
            "DELETE FROM users",
            "DELETE FROM users WHERE id = 5",
            "DELETE FROM users WHERE active = 0 AND created_at < '2020-01-01'",

            # CREATE TABLE
            "CREATE TABLE users (id INT, name VARCHAR(100))",
            "CREATE TABLE products (id INT PRIMARY KEY, name VARCHAR(100), price DECIMAL(10, 2))",

            # DROP TABLE
            "DROP TABLE users",
            "DROP TABLE IF EXISTS users",

            # LIMIT and OFFSET
            "SELECT * FROM users LIMIT 10",
            "SELECT * FROM users LIMIT 10 OFFSET 20",

            # Complex expressions
            "SELECT id * 2 AS doubled FROM numbers",
            "SELECT price * quantity AS total FROM order_items",
            "SELECT CONCAT(first_name, ' ', last_name) AS full_name FROM users",

            # CASE statements
            "SELECT CASE WHEN age < 18 THEN 'minor' ELSE 'adult' END FROM users",
            "SELECT CASE status WHEN 'active' THEN 1 WHEN 'inactive' THEN 0 ELSE -1 END FROM accounts",

            # EXISTS
            "SELECT * FROM users WHERE EXISTS (SELECT 1 FROM orders WHERE orders.user_id = users.id)",

            # UNION
            "SELECT name FROM users UNION SELECT name FROM admins",
            "SELECT id FROM products UNION ALL SELECT id FROM archived_products",

            # Multiple conditions
            "SELECT * FROM orders WHERE status = 'shipped' AND total > 100 OR priority = 'high'",

            # Nested functions
            "SELECT UPPER(TRIM(name)) FROM users",

            # NULL checks
            "SELECT * FROM users WHERE email IS NOT NULL",

            # String literals with escaping
            "SELECT * FROM users WHERE name = 'O''Brien'",

            # Numeric expressions
            "SELECT * FROM products WHERE price > 10.5 AND price < 100.99",
            "SELECT * FROM items WHERE quantity >= 0",

            # Date/time
            "SELECT * FROM events WHERE event_date > '2024-01-01'",

            # Wildcard with table prefix
            "SELECT users.* FROM users JOIN orders ON users.id = orders.user_id",

            # Multiple JOINs with WHERE
            "SELECT * FROM users u JOIN orders o ON u.id = o.user_id WHERE u.active = 1",

            # Complex GROUP BY
            "SELECT region, category, SUM(sales) FROM transactions GROUP BY region, category",

            # Arithmetic in SELECT
            "SELECT price + tax AS total_price FROM products",
            "SELECT quantity - shipped AS remaining FROM inventory",
            "SELECT price / 2 AS half_price FROM products",

            # IN with subquery
            "SELECT * FROM customers WHERE country IN (SELECT country FROM offices)",

            # Multiple aggregate functions
            "SELECT COUNT(*), AVG(salary), MIN(age), MAX(experience) FROM employees",

            # Complex WHERE with parentheses
            "SELECT * FROM users WHERE (status = 'active' OR status = 'pending') AND age > 18",

            # Comparison operators
            "SELECT * FROM products WHERE price <> 0",
            "SELECT * FROM items WHERE stock <= 10",

            # ORDER BY with expression
            "SELECT * FROM products ORDER BY price * quantity DESC",

            # String functions
            "SELECT LENGTH(name) FROM users",
            "SELECT SUBSTRING(description, 1, 100) FROM articles",

            # Cross join
            "SELECT * FROM table1 CROSS JOIN table2",

            # Aliasing
            "SELECT u.name, o.total FROM users u, orders o WHERE u.id = o.user_id",

            # Column arithmetic
            "SELECT (price * 1.1) AS price_with_tax FROM products",
        ]

        return test_cases
