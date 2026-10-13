import pandas as pd
import os
import numpy as np
import sys

class Solution:
    """Parameterized adaptive margin. Set BASE_MARGIN and EXPONENT via env vars."""
    def __init__(self):
        self.eval_routing = {}
        self.default_route = "mid"
        self._load_data()

    def _load_data(self):
        paths = [
            "resources/reference_data.csv",
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "resources", "reference_data.csv"),
        ]
        df = None
        for p in paths:
            try:
                if os.path.exists(p):
                    df = pd.read_csv(p)
                    break
            except Exception:
                continue
        if df is None:
            return

        tier_map = {
            "cheap": "mistralai/mistral-7b-chat",
            "mid": "mistralai/mixtral-8x7b-chat",
            "expensive": "gpt-4-1106-preview",
        }
        model_to_tier = {v: k for k, v in tier_map.items()}
        lambda_val = 150.0
        oracle_weight = 0.05

        # Read params from env
        base_margin = float(os.environ.get('BASE_MARGIN', '0.06'))
        exponent = float(os.environ.get('EXPONENT', '0.5'))

        eval_sizes = df.groupby('eval_name').size()
        median_size = eval_sizes.median()

        for eval_name in df['eval_name'].unique():
            eval_df = df[df['eval_name'] == eval_name]
            n_samples = len(eval_df)
            tier_scores = {}
            for tier, model in tier_map.items():
                if model in eval_df.columns:
                    acc = eval_df[model].mean()
                    cost_col = f"{model}|total_cost"
                    avg_cost = eval_df[cost_col].mean() if cost_col in eval_df.columns else 0
                    tier_scores[tier] = acc - lambda_val * avg_cost

            if not tier_scores:
                continue

            if 'oracle_model_to_route_to' in eval_df.columns:
                oracle_tiers = eval_df['oracle_model_to_route_to'].map(model_to_tier).dropna()
                tc = oracle_tiers.value_counts(normalize=True)
                weighted = {}
                for tier in ["cheap", "mid", "expensive"]:
                    oracle_frac = tc.get(tier, 0)
                    if tier in tier_scores:
                        weighted[tier] = tier_scores[tier] + oracle_weight * oracle_frac
                if weighted:
                    tier_scores = weighted

            sorted_tiers = sorted(tier_scores.items(), key=lambda x: x[1], reverse=True)
            best_tier = sorted_tiers[0][0]

            margin_threshold = base_margin * (median_size / max(n_samples, 1)) ** exponent

            if len(sorted_tiers) > 1:
                margin = sorted_tiers[0][1] - sorted_tiers[1][1]
                if margin < margin_threshold:
                    mid_score = tier_scores.get("mid", float('-inf'))
                    if best_tier != "mid" and (sorted_tiers[0][1] - mid_score) < margin_threshold:
                        self.eval_routing[eval_name] = "mid"
                    else:
                        second_tier = sorted_tiers[1][0]
                        tier_order = {"cheap": 0, "mid": 1, "expensive": 2}
                        if tier_order.get(second_tier, 1) < tier_order.get(best_tier, 1):
                            self.eval_routing[eval_name] = second_tier
                        else:
                            self.eval_routing[eval_name] = best_tier
                else:
                    self.eval_routing[eval_name] = best_tier
            else:
                self.eval_routing[eval_name] = best_tier

    def solve(self, query, eval_name, candidate_models):
        choice = self.eval_routing.get(eval_name, self.default_route)
        if choice in candidate_models:
            return choice
        return "mid" if "mid" in candidate_models else candidate_models[0]
