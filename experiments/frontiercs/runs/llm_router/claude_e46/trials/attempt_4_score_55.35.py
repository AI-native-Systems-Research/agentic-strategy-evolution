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

        # Per-eval best tier (baseline)
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

        # Build routing rules per eval_name
        # For each eval, compute per-tier expected score in different query buckets
        # Use multiple features: prompt length, word count, has code indicators
        self._eval_rules = {}

        for eval_name in df['eval_name'].unique():
            edf = df[df['eval_name'] == eval_name].copy()
            if len(edf) < 20:
                continue

            # Compute features
            edf = edf.copy()
            edf['plen'] = edf['prompt'].fillna('').str.len()
            median_len = edf['plen'].median()

            default_tier = self._eval_best[eval_name]

            # Check if we can improve by splitting on prompt length
            # Short prompts: length <= median
            # Long prompts: length > median
            rules = []

            for split_val in [median_len]:
                short_mask = edf['plen'] <= split_val
                long_mask = ~short_mask

                for mask, label in [(short_mask, 'short'), (long_mask, 'long')]:
                    subset = edf[mask]
                    if len(subset) < 5:
                        continue

                    best_score = float('-inf')
                    best_tier = default_tier
                    for tier, model in self._tier_map.items():
                        if model in model_cols and model in cost_cols:
                            acc = subset[model].mean()
                            cost = subset[cost_cols[model]].mean()
                            score = acc - 150.0 * cost
                            if score > best_score:
                                best_score = score
                                best_tier = tier

                    if best_tier != default_tier:
                        rules.append({
                            'feature': 'plen',
                            'op': '<=' if label == 'short' else '>',
                            'value': split_val,
                            'tier': best_tier,
                        })

            if rules:
                self._eval_rules[eval_name] = {
                    'default': default_tier,
                    'rules': rules,
                    'median_len': median_len,
                }

    def solve(self, query: str, eval_name: str, candidate_models: list) -> str:
        self._load()

        # Check if eval has rules
        if eval_name in self._eval_rules:
            rules = self._eval_rules[eval_name]
            plen = len(str(query))

            for rule in rules['rules']:
                if rule['feature'] == 'plen':
                    if rule['op'] == '<=' and plen <= rule['value']:
                        tier = rule['tier']
                        if tier in candidate_models:
                            return tier
                    elif rule['op'] == '>' and plen > rule['value']:
                        tier = rule['tier']
                        if tier in candidate_models:
                            return tier

        # Fallback to per-eval best
        best = self._eval_best.get(eval_name, "mid")
        return best if best in candidate_models else "mid"
