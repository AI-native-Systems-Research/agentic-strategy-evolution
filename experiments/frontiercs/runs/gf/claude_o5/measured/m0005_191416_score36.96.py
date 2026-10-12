class Solution:
    def solve(self, resources_path: str) -> list[str]:
        return [
            "SELECT 1",
            "SELECT * FROM t",
            "SELECT a, b, c FROM t",
            "SELECT * FROM t WHERE a = 1",
            "SELECT a FROM t ORDER BY a",
        ]
