class Solution:
    def solve(self, resources_path):
        """Dense strategy: 20 compound statements with high construct density."""
        return [
            # Complex SELECT with multiple clauses and joins
            "SELECT DISTINCT t1.id, t2.name, COUNT(*), SUM(t1.value), AVG(t1.value), MAX(t2.score), MIN(t2.score) FROM table1 AS t1 INNER JOIN table2 AS t2 ON t1.id = t2.ref_id WHERE t1.value > 100 AND t2.status = 'active' AND t1.category IN ('A', 'B', 'C') GROUP BY t1.id, t2.name HAVING COUNT(*) > 5 AND SUM(t1.value) < 10000 ORDER BY t1.id DESC, COUNT(*) ASC LIMIT 50 OFFSET 10;",

            # Multiple JOIN types with subquery
            "SELECT a.*, b.total FROM users a LEFT JOIN (SELECT user_id, COUNT(*) as total FROM orders WHERE amount > 50 GROUP BY user_id) b ON a.id = b.user_id RIGHT JOIN profiles p ON a.profile_id = p.id WHERE a.created_at BETWEEN '2020-01-01' AND '2023-12-31' ORDER BY b.total DESC NULLS LAST;",

            # Complex nested subqueries with various operators
            "SELECT * FROM products WHERE price > (SELECT AVG(price) FROM products WHERE category = 'electronics') AND id IN (SELECT product_id FROM reviews WHERE rating >= 4.5) AND stock_quantity BETWEEN 10 AND 1000 OR (discount_pct > 20 AND brand NOT IN (SELECT name FROM banned_brands));",

            # INSERT with complex expressions
            "INSERT INTO analytics (user_id, metric_value, computed_score, category, timestamp) VALUES (123, 45.67, 45.67 * 1.5 + 10, CASE WHEN 45.67 > 50 THEN 'high' WHEN 45.67 > 30 THEN 'medium' ELSE 'low' END, datetime('now'));",

            # UPDATE with complex WHERE and arithmetic
            "UPDATE inventory SET quantity = quantity - 5, last_updated = datetime('now'), status = CASE WHEN quantity - 5 < 10 THEN 'low_stock' WHEN quantity - 5 < 50 THEN 'medium' ELSE 'sufficient' END WHERE product_id IN (SELECT id FROM products WHERE category = 'seasonal') AND warehouse_id = 7 AND quantity >= 5;",

            # DELETE with subquery and multiple conditions
            "DELETE FROM temp_records WHERE created_at < date('now', '-30 days') AND status = 'processed' AND id NOT IN (SELECT record_id FROM audit_log WHERE action = 'keep') AND (priority < 5 OR archived = 1);",

            # Complex aggregations with CASE expressions
            "SELECT category, COUNT(*) as total, SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) as active_count, AVG(CASE WHEN price IS NOT NULL THEN price ELSE 0 END) as avg_price, MAX(created_at) as latest, MIN(created_at) as earliest FROM items WHERE deleted_at IS NULL GROUP BY category HAVING COUNT(*) > 10 ORDER BY total DESC;",

            # Self-join with complex conditions
            "SELECT e1.name as employee, e2.name as manager, e1.salary, e1.department FROM employees e1 LEFT JOIN employees e2 ON e1.manager_id = e2.id WHERE e1.salary > 50000 AND e1.hire_date > '2020-01-01' AND (e1.department = 'engineering' OR e1.department = 'product') ORDER BY e1.salary DESC;",

            # UNION with multiple SELECTs
            "SELECT id, name, 'customer' as type, balance as amount FROM customers WHERE status = 'active' UNION SELECT id, vendor_name as name, 'vendor' as type, credit_limit as amount FROM vendors WHERE approved = 1 UNION SELECT id, partner_name as name, 'partner' as type, contract_value as amount FROM partners WHERE active = 1 ORDER BY amount DESC LIMIT 100;",

            # Complex string operations and functions
            "SELECT UPPER(name) as name_upper, LOWER(email) as email_lower, LENGTH(description) as desc_len, SUBSTR(phone, 1, 3) as area_code, REPLACE(address, 'Street', 'St') as address_short FROM contacts WHERE LENGTH(name) > 5 AND email LIKE '%@company.com' AND phone IS NOT NULL;",

            # Nested aggregations with DISTINCT
            "SELECT country, COUNT(DISTINCT city) as unique_cities, COUNT(DISTINCT customer_id) as unique_customers, SUM(DISTINCT order_value) as total_value FROM sales WHERE order_date >= '2023-01-01' AND status IN ('completed', 'shipped') GROUP BY country HAVING COUNT(DISTINCT customer_id) >= 100;",

            # Complex boolean logic with NULL handling
            "SELECT * FROM transactions WHERE (amount > 1000 AND currency = 'USD') OR (amount > 800 AND currency = 'EUR') AND processed_at IS NOT NULL AND (refunded = 0 OR refunded IS NULL) AND NOT (status = 'cancelled' AND reason LIKE '%fraud%') ORDER BY amount DESC, processed_at ASC;",

            # Window functions simulation with subquery
            "SELECT user_id, order_id, amount, order_date, (SELECT COUNT(*) FROM orders o2 WHERE o2.user_id = o1.user_id AND o2.order_date <= o1.order_date) as order_sequence FROM orders o1 WHERE amount > 100 ORDER BY user_id, order_date;",

            # Multiple aggregate functions with filtering
            "SELECT department, position, COUNT(*) as headcount, SUM(salary) as total_salary, AVG(salary) as avg_salary, MIN(salary) as min_salary, MAX(salary) as max_salary, SUM(bonus) as total_bonus FROM employees WHERE employment_status = 'active' AND hire_date < '2023-01-01' GROUP BY department, position HAVING AVG(salary) > 60000 ORDER BY total_salary DESC;",

            # Complex CASE expression as column
            "SELECT product_id, name, price, stock, CASE WHEN stock = 0 THEN 'out_of_stock' WHEN stock < 10 THEN 'low' WHEN stock < 50 THEN 'medium' WHEN stock < 200 THEN 'high' ELSE 'overstocked' END as stock_status, CASE WHEN price < 20 THEN 'budget' WHEN price < 100 THEN 'standard' WHEN price < 500 THEN 'premium' ELSE 'luxury' END as price_tier FROM products;",

            # IN with subquery and NOT IN
            "SELECT * FROM articles WHERE author_id IN (SELECT id FROM authors WHERE verified = 1 AND reputation > 100) AND category_id NOT IN (SELECT category_id FROM blocked_categories) AND publish_date BETWEEN '2023-01-01' AND '2023-12-31' AND (views > 1000 OR likes > 100);",

            # Complex date/time operations
            "SELECT user_id, login_date, logout_date, julianday(logout_date) - julianday(login_date) as session_days, strftime('%Y-%m', login_date) as month, strftime('%H', login_date) as hour FROM sessions WHERE login_date >= date('now', '-90 days') AND logout_date IS NOT NULL ORDER BY session_days DESC;",

            # Multiple levels of subqueries
            "SELECT * FROM orders WHERE customer_id IN (SELECT customer_id FROM purchases WHERE total_spent > (SELECT AVG(total_spent) FROM purchases WHERE year = 2023) AND purchase_count > 5) AND order_status = 'delivered' ORDER BY order_date DESC LIMIT 50;",

            # Complex arithmetic and comparisons
            "SELECT id, quantity, price, quantity * price as subtotal, quantity * price * 0.9 as discounted, quantity * price * 0.1 as savings FROM order_items WHERE quantity * price > 100 AND (quantity > 10 OR price > 50) AND quantity * price * 0.9 < 1000 ORDER BY subtotal DESC;",

            # Full-text search patterns with wildcards
            "SELECT id, title, description, author FROM documents WHERE (title LIKE '%analysis%' OR title LIKE '%report%') AND description LIKE '%data%' AND author NOT LIKE '%bot%' AND (status = 'published' OR status = 'featured') ORDER BY created_at DESC LIMIT 25;"
        ]
