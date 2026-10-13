import pandas as pd
import os

class Solution:
    def __init__(self):
        self._loaded = False
        self._eval_tier_stats = {}

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
                model_name = c.replace('|total_cost', '')
                cost_cols[model_name] = c
            elif c not in ['sample_id', 'prompt', 'eval_name', 'oracle_model_to_route_to'] and '|' not in c:
                model_cols.append(c)

        avg_costs = {}
        for m in model_cols:
            if m in cost_cols:
                avg_costs[m] = df[cost_cols[m]].mean()

        if not avg_costs:
            return

        self._avg_costs = avg_costs
        self._model_cols = model_cols
        self._cost_cols = cost_cols

        # For each eval_name, compute per-tier score = accuracy - 150*cost
        for eval_name in df['eval_name'].unique():
            edf = df[df['eval_name'] == eval_name]
            tier_stats = {}
            for m in model_cols:
                if m in cost_cols:
                    acc = edf[m].mean()
                    cost = edf[cost_cols[m]].mean()
                    score = acc - 150.0 * cost
                    tier = self._get_tier(m)
                    if tier not in tier_stats or score > tier_stats[tier]:
                        tier_stats[tier] = score
            self._eval_tier_stats[eval_name] = tier_stats

    def _get_tier(self, model_name):
        cost = self._avg_costs.get(model_name, 0)
        sorted_costs = sorted(self._avg_costs.values())
        if not sorted_costs:
            return "cheap"
        min_c = sorted_costs[0]
        if min_c == 0:
            min_c = 1e-8
        ratio = cost / min_c
        if ratio < 5:
            return "cheap"
        elif ratio < 30:
            return "mid"
        else:
            return "expensive"

    def solve(self, query: str, eval_name: str, candidate_models: list) -> str:
        self._load()

        stats = self._eval_tier_stats.get(eval_name, {})
        if not stats:
            return "cheap" if "cheap" in candidate_models else candidate_models[0]

        best_tier = max(candidate_models, key=lambda t: stats.get(t, float('-inf')))
        return best_tier
