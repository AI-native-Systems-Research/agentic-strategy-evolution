class Solution:
    def solve(self, resources_path: str):
        """
        H-Main: 36 cases = iter-4's proven 35-case set + 1 deep-analysis edge case
        Testing whether hybrid targeting (statement + tokenizer-edge) breaks 59 pts ceiling
        """
        tests = []

        # === STATEMENT TYPES (5 cases) ===
        tests.append("SELECT id, name FROM users;")
        tests.append("INSERT INTO users (id, name) VALUES (1, 'Alice');")
        tests.append("UPDATE users SET name = 'Bob' WHERE id = 1;")
        tests.append("DELETE FROM users WHERE id = 1;")
        tests.append("CREATE TABLE users (id INT PRIMARY KEY, name TEXT NOT NULL);")

        # === COMMON CLAUSES (8 cases) ===
        tests.append("SELECT * FROM users WHERE id > 5 AND name = 'Alice';")
        tests.append("SELECT u.name, o.amount FROM users u INNER JOIN orders o ON u.id = o.user_id;")
        tests.append("SELECT u.name, o.amount FROM users u LEFT JOIN orders o ON u.id = o.user_id;")
        tests.append("SELECT u.name, o.amount FROM users u RIGHT JOIN orders o ON u.id = o.user_id;")
        tests.append("SELECT user_id, COUNT(*) FROM orders GROUP BY user_id;")
        tests.append("SELECT user_id, COUNT(*) FROM orders GROUP BY user_id HAVING COUNT(*) > 5;")
        tests.append("SELECT * FROM users ORDER BY name ASC, id DESC;")
        tests.append("SELECT * FROM users ORDER BY id LIMIT 10 OFFSET 5;")

        # === COMMON EXPRESSIONS (10 cases) ===
        tests.append("SELECT price * quantity, price + tax FROM products;")
        tests.append("SELECT * FROM users WHERE age >= 18 AND age <= 65;")
        tests.append("SELECT * FROM users WHERE id IN (1, 2, 3, 5, 8, 13);")
        tests.append("SELECT * FROM orders WHERE amount BETWEEN 100 AND 500;")
        tests.append("SELECT * FROM users WHERE name LIKE 'A%';")
        tests.append("SELECT * FROM users WHERE email IS NOT NULL;")
        tests.append("SELECT COUNT(*), SUM(amount), AVG(amount), MIN(amount), MAX(amount) FROM orders;")
        tests.append("SELECT UPPER(name), LOWER(email), LENGTH(name) FROM users;")
        tests.append("SELECT * FROM users WHERE NOT (age < 18 OR status = 'inactive');")
        tests.append("SELECT * FROM users WHERE id IN (SELECT user_id FROM orders WHERE amount > 100);")

        # === RARE CONSTRUCTS (7 cases) ===
        tests.append("SELECT sub.total FROM (SELECT SUM(amount) AS total FROM orders) AS sub;")
        tests.append("SELECT * FROM users WHERE EXISTS (SELECT 1 FROM orders WHERE orders.user_id = users.id);")
        tests.append("SELECT DISTINCT category FROM products;")
        tests.append("SELECT u.name, o.amount, p.name FROM users u JOIN orders o ON u.id = o.user_id JOIN products p ON o.product_id = p.id;")
        tests.append("SELECT id, amount * 0.9 FROM orders WHERE amount > 500 AND status = 'pending';")
        tests.append("SELECT * FROM users WHERE id NOT IN (SELECT user_id FROM banned_users);")
        tests.append("SELECT name AS user_name, email AS contact_email FROM users;")

        # === EDGE CASES (5 cases) ===
        tests.append("SELECT * FROM users WHERE id IN (SELECT user_id FROM orders WHERE amount IN (SELECT value FROM thresholds));")
        tests.append("INSERT INTO users (id, name) VALUES (1, 'Alice'), (2, 'Bob'), (3, 'Charlie');")
        tests.append("SELECT * FROM orders WHERE (amount > 100 OR priority = 'high') AND status = 'pending' AND user_id > 0 AND created_at IS NOT NULL;")
        tests.append("SELECT u.name, o.amount FROM users u FULL OUTER JOIN orders o ON u.id = o.user_id;")
        tests.append("CREATE TABLE products (id INT PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, price REAL DEFAULT 0.0 CHECK (price >= 0));")

        # === DEEP-ANALYSIS TOKENIZER EDGE CASE (+1 case, total 36) ===
        # Targeting uncovered tokenizer branches: scientific notation (exponential numeric literals)
        # Based on hypothesis that simple literals (1, 'a', 2.5) in 35-case don't exercise
        # scientific notation tokenization logic (e.g., 1.23e-4, 5E+10)
        tests.append("SELECT 1.23e-4, 5E+10, 9.87e6, 0.001e-3 FROM scientific_data;")

        return tests
