import pandas as pd
import numpy as np
import os
import re

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

        # Per-eval best tier
        self._eval_best = {}
        for eval_name in df['eval_name'].unique():
            edf = df[df['eval_name'] == eval_name]
            best_score = float('-inf')
            best_tier = "mid"
            for tier, model in self._tier_map.items():
                if model in model_cols and model in cost_cols:
                    acc = edf[model].mean()
                    cost = edf[cost_cols[model]].mean()
                    score = acc - 150.0 * cost
                    if score > best_score:
                        best_score = score
                        best_tier = tier
            self._eval_best[eval_name] = best_tier

        # Cross-validated length-based rules
        self._eval_rules = {}

        for eval_name in df['eval_name'].unique():
            edf = df[df['eval_name'] == eval_name].copy()
            if len(edf) < 40:
                continue

            default_tier = self._eval_best[eval_name]
            edf['plen'] = edf['prompt'].fillna('').str.len()

            # 5-fold cross-validation to find robust splits
            n = len(edf)
            indices = np.arange(n)
            np.random.seed(42)
            np.random.shuffle(indices)
            fold_size = n // 5

            best_rule = None
            best_cv_improvement = 0

            for pct in [25, 33, 50, 67, 75]:
                split_val = np.percentile(edf['plen'].values, pct)

                cv_improvements = []
                for fold in range(5):
                    val_idx = indices[fold * fold_size:(fold + 1) * fold_size]
                    train_idx = np.concatenate([indices[:fold * fold_size], indices[(fold + 1) * fold_size:]])

                    train_df = edf.iloc[train_idx]
                    val_df = edf.iloc[val_idx]

                    if len(val_df) < 5:
                        continue

                    # Find best tiers for short/long on TRAINING fold
                    train_short = train_df[train_df['plen'] <= split_val]
                    train_long = train_df[train_df['plen'] > split_val]

                    short_best = default_tier
                    long_best = default_tier

                    if len(train_short) >= 10:
                        best_s = float('-inf')
                        for tier, model in self._tier_map.items():
                            if model in model_cols and model in cost_cols:
                                acc = train_short[model].mean()
                                cost = train_short[cost_cols[model]].mean()
                                s = acc - 150.0 * cost
                                if s > best_s:
                                    best_s = s
                                    short_best = tier

                    if len(train_long) >= 10:
                        best_s = float('-inf')
                        for tier, model in self._tier_map.items():
                            if model in model_cols and model in cost_cols:
                                acc = train_long[model].mean()
                                cost = train_long[cost_cols[model]].mean()
                                s = acc - 150.0 * cost
                                if s > best_s:
                                    best_s = s
                                    long_best = tier

                    if short_best == default_tier and long_best == default_tier:
                        cv_improvements.append(0)
                        continue

                    # Evaluate on validation fold
                    val_short = val_df[val_df['plen'] <= split_val]
                    val_long = val_df[val_df['plen'] > split_val]

                    def eval_score(subset, tier):
                        if len(subset) == 0:
                            return 0
                        model = self._tier_map[tier]
                        if model in model_cols and model in cost_cols:
                            acc = subset[model].mean()
                            cost = subset[cost_cols[model]].mean()
                            return (acc - 150.0 * cost) * len(subset)
                        return 0

                    new_score = eval_score(val_short, short_best) + eval_score(val_long, long_best)
                    baseline_score = eval_score(val_df, default_tier) * 1.0
                    baseline_score = eval_score(val_short, default_tier) + eval_score(val_long, default_tier)

                    cv_improvements.append(new_score - baseline_score)

                if len(cv_improvements) >= 3:
                    avg_improvement = np.mean(cv_improvements)
                    # Only keep rule if consistently positive across folds
                    n_positive = sum(1 for x in cv_improvements if x > 0)
                    if avg_improvement > best_cv_improvement and n_positive >= 3:
                        # Re-compute tiers on full data
                        full_short = edf[edf['plen'] <= split_val]
                        full_long = edf[edf['plen'] > split_val]

                        short_tier = default_tier
                        long_tier = default_tier

                        if len(full_short) >= 10:
                            best_s = float('-inf')
                            for tier, model in self._tier_map.items():
                                if model in model_cols and model in cost_cols:
                                    acc = full_short[model].mean()
                                    cost = full_short[cost_cols[model]].mean()
                                    s = acc - 150.0 * cost
                                    if s > best_s:
                                        best_s = s
                                        short_tier = tier

                        if len(full_long) >= 10:
                            best_s = float('-inf')
                            for tier, model in self._tier_map.items():
                                if model in model_cols and model in cost_cols:
                                    acc = full_long[model].mean()
                                    cost = full_long[cost_cols[model]].mean()
                                    s = acc - 150.0 * cost
                                    if s > best_s:
                                        best_s = s
                                        long_tier = tier

                        if short_tier != long_tier:
                            best_cv_improvement = avg_improvement
                            best_rule = {
                                'split_val': split_val,
                                'short_tier': short_tier,
                                'long_tier': long_tier,
                            }

            if best_rule:
                self._eval_rules[eval_name] = best_rule

    def solve(self, query: str, eval_name: str, candidate_models: list) -> str:
        self._load()

        if eval_name in self._eval_rules:
            rule = self._eval_rules[eval_name]
            plen = len(str(query))
            if plen <= rule['split_val']:
                tier = rule['short_tier']
            else:
                tier = rule['long_tier']
            if tier in candidate_models:
                return tier

        best = self._eval_best.get(eval_name, "mid")
        return best if best in candidate_models else "mid"
