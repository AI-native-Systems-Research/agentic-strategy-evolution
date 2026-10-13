import pandas as pd
import os

class Solution:
    def __init__(self):
        self._loaded = False

    def _load(self):
        if self._loaded:
            return
        self._loaded = True

        paths = [
            "resources/reference_data.csv",
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "resources", "reference_data.csv"),
        ]
        df = None
        for p in paths:
            try:
                df = pd.read_csv(p)
                break
            except:
                continue
        if df is None:
            return

        all_cols = df.columns.tolist()
        model_cols = []
        cost_cols = {}
        for c in all_cols:
            if '|total_cost' in c:
                cost_cols[c.replace('|total_cost', '')] = c
            elif c not in ['sample_id', 'prompt', 'eval_name', 'oracle_model_to_route_to'] and '|' not in c:
                model_cols.append(c)

        self._tier_map = {
            "cheap": "mistralai/mistral-7b-chat",
            "mid": "mistralai/mixtral-8x7b-chat",
            "expensive": "gpt-4-1106-preview",
        }

        self._eval_best = {}
        self._eval_tier_score = {}
        for eval_name in df['eval_name'].unique():
            edf = df[df['eval_name'] == eval_name]
            best_score = float('-inf')
            best_tier = "mid"
            tier_scores = {}
            for tier, model in self._tier_map.items():
                if model in model_cols and model in cost_cols:
                    acc = edf[model].mean()
                    cost = edf[cost_cols[model]].mean()
                    score = acc - 150.0 * cost
                    tier_scores[tier] = score
                    if score > best_score:
                        best_score = score
                        best_tier = tier
            self._eval_best[eval_name] = best_tier
            self._eval_tier_score[eval_name] = tier_scores

    def solve(self, query: str, eval_name: str, candidate_models: list) -> str:
        self._load()
        best = self._eval_best.get(eval_name, "expensive")
        return best if best in candidate_models else "mid"
