class Solution:
    def solve(self, resources_path: str):
        """
        H-Super-Additivity: 36 cases = 33 statement-focused + 3 tokenizer-edge
        Testing whether statement-first and tokenizer-edge strategies are orthogonal
        (super-additive coverage gain vs redundancy)
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

        # === EDGE CASES (3 cases) ===
        # Removed nested subquery and complex CREATE TABLE to make room for tokenizer tests
        tests.append("INSERT INTO users (id, name) VALUES (1, 'Alice'), (2, 'Bob'), (3, 'Charlie');")
        tests.append("SELECT * FROM orders WHERE (amount > 100 OR priority = 'high') AND status = 'pending' AND user_id > 0 AND created_at IS NOT NULL;")
        tests.append("SELECT u.name, o.amount FROM users u FULL OUTER JOIN orders o ON u.id = o.user_id;")

        # === TOKENIZER EDGE CASES (+3 cases, total 36) ===
        # Test 1: Hexadecimal literals - exercises hex tokenization path
        tests.append("SELECT 0xFF, 0x1A2B, 0xDEADBEEF FROM hex_data;")

        # Test 2: Scientific notation - exercises exponential numeric tokenization
        tests.append("SELECT 1.23e-4, 5E+10, 9.87e6, 0.001e-3 FROM scientific_data;")

        # Test 3: Escaped strings - exercises escape sequence handling
        tests.append("SELECT 'can''t', 'tab\ttab', 'quote\"test', 'backslash\\test' FROM string_data;")

        return tests
