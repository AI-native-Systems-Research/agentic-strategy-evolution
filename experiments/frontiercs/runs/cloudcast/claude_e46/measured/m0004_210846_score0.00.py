import os

class Solution:
    def solve(self, spec_path: str = None) -> dict:
        algo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "algorithm.py")
        return {"program_path": algo_path}
