import os
import sys

class Solution:
    def solve(self, resources_path: str) -> list[str]:
        parser_path = os.path.join(resources_path, "sql_engine", "parser.py")
        tokenizer_path = os.path.join(resources_path, "sql_engine", "tokenizer.py")
        ast_path = os.path.join(resources_path, "sql_engine", "ast_nodes.py")
        grammar_path = os.path.join(resources_path, "sql_grammar.txt")

        for name, path in [("parser", parser_path), ("tokenizer", tokenizer_path),
                           ("ast", ast_path), ("grammar", grammar_path)]:
            try:
                with open(path, "r") as f:
                    content = f.read()
                print(f"\n{'='*60}\n{name}: {path}\n{'='*60}")
                print(content[:5000])
                if len(content) > 5000:
                    print(f"\n... ({len(content)} total chars)")
            except Exception as e:
                print(f"{name}: ERROR {e}")

        return ["SELECT 1"]

if __name__ == "__main__":
    s = Solution()
    # Try common resource paths
    for rp in ["/tmp/resources", "resources", "../resources"]:
        if os.path.exists(rp):
            s.solve(rp)
            break
