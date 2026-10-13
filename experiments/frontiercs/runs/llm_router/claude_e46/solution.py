import pandas as pd
import numpy as np
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

        # Global accuracy and cost per tier
        global_acc = {}
        global_cost = {}
        for tier, model in self._tier_map.items():
            if model in model_cols:
                global_acc[tier] = df[model].mean()
            if model in cost_cols:
                global_cost[tier] = df[cost_cols[model]].mean()

        # Per-eval with Bayesian shrinkage
        # Shrink per-eval accuracy toward global average
        # Shrinkage strength: higher = more shrinkage
        shrinkage = 5  # equivalent to 5 pseudo-observations from global

        self._eval_best = {}

        for eval_name in df['eval_name'].unique():
            edf = df[df['eval_name'] == eval_name]
            n = len(edf)
            best_score = float('-inf')
            best_tier = "mid"

            for tier, model in self._tier_map.items():
                if model in model_cols and model in cost_cols:
                    # Shrunk accuracy estimate
                    raw_acc = edf[model].mean()
                    shrunk_acc = (raw_acc * n + global_acc[tier] * shrinkage) / (n + shrinkage)
                    cost = edf[cost_cols[model]].mean()
                    score = shrunk_acc - 150.0 * cost
                    if score > best_score:
                        best_score = score
                        best_tier = tier

            self._eval_best[eval_name] = best_tier

        # Also store global best for fallback
        best_global_score = float('-inf')
        self._global_best = "mid"
        for tier in self._tier_map:
            if tier in global_acc and tier in global_cost:
                score = global_acc[tier] - 150.0 * global_cost[tier]
                if score > best_global_score:
                    best_global_score = score
                    self._global_best = tier

    def solve(self, query: str, eval_name: str, candidate_models: list) -> str:
        self._load()
        best = self._eval_best.get(eval_name, self._global_best)
        return best if best in candidate_models else "mid"
