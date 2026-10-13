import pandas as pd
import numpy as np
import os
import re

class Solution:
    def __init__(self):
        self._loaded = False

    def _extract_features(self, prompt):
        """Extract routing-relevant features from prompt text."""
        s = str(prompt)
        words = s.split()
        nwords = len(words)
        nchars = len(s)
        nlines = s.count('\n') + 1

        has_code = 1 if any(kw in s for kw in ['def ', 'class ', 'import ', 'return ', 'function ', 'var ', 'int ', 'void ']) else 0
        has_mcq = 1 if re.search(r'\n[A-E][).:]', s) else 0
        has_math = 1 if re.search(r'[+\-*/=<>]{2,}|\\frac|\\sum|\\int|\d+\.\d+', s) else 0
        digit_ratio = sum(c.isdigit() for c in s) / max(nchars, 1)
        upper_ratio = sum(c.isupper() for c in s) / max(nchars, 1)
        avg_word_len = np.mean([len(w) for w in words]) if words else 0
        unique_word_ratio = len(set(w.lower() for w in words)) / max(nwords, 1)
        n_questions = s.count('?')
        n_parens = s.count('(') + s.count(')')
        n_brackets = s.count('[') + s.count(']')

        return {
            'nchars': nchars,
            'nwords': nwords,
            'nlines': nlines,
            'has_code': has_code,
            'has_mcq': has_mcq,
            'has_math': has_math,
            'digit_ratio': digit_ratio,
            'upper_ratio': upper_ratio,
            'avg_word_len': avg_word_len,
            'unique_word_ratio': unique_word_ratio,
            'n_questions': n_questions,
            'n_parens': n_parens,
            'n_brackets': n_brackets,
        }

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

        # Precompute features for all rows
        features_list = []
        for _, row in df.iterrows():
            features_list.append(self._extract_features(row.get('prompt', '')))
        feat_df = pd.DataFrame(features_list)
        feat_cols = list(feat_df.columns)

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

        # Build a simple decision stump per eval_name
        # For each eval, find the best single-feature split that improves over default
        self._eval_tree = {}

        for eval_name in df['eval_name'].unique():
            eval_mask = df['eval_name'] == eval_name
            edf = df[eval_mask]
            efeat = feat_df[eval_mask]

            if len(edf) < 30:
                continue

            default_tier = self._eval_best[eval_name]

            # Compute default score
            def compute_tier_score(subset_df, tier):
                model = self._tier_map[tier]
                if model in model_cols and model in cost_cols:
                    acc = subset_df[model].mean()
                    cost = subset_df[cost_cols[model]].mean()
                    return acc - 150.0 * cost
                return float('-inf')

            default_score_total = compute_tier_score(edf, default_tier) * len(edf)

            best_improvement = 0
            best_split = None

            for feat in feat_cols:
                values = efeat[feat].values
                unique_vals = np.unique(values)
                if len(unique_vals) < 2:
                    continue

                # Try percentile-based split points
                for pct in [25, 50, 75]:
                    split_val = np.percentile(values, pct)
                    left_mask = values <= split_val
                    right_mask = ~left_mask

                    n_left = left_mask.sum()
                    n_right = right_mask.sum()
                    if n_left < 10 or n_right < 10:
                        continue

                    left_df = edf[left_mask]
                    right_df = edf[right_mask]

                    # Find best tier for each side
                    best_left_score = float('-inf')
                    best_left_tier = default_tier
                    best_right_score = float('-inf')
                    best_right_tier = default_tier

                    for tier in self._tier_map:
                        ls = compute_tier_score(left_df, tier)
                        if ls > best_left_score:
                            best_left_score = ls
                            best_left_tier = tier

                        rs = compute_tier_score(right_df, tier)
                        if rs > best_right_score:
                            best_right_score = rs
                            best_right_tier = tier

                    new_total = best_left_score * n_left + best_right_score * n_right
                    improvement = new_total - default_score_total

                    if improvement > best_improvement:
                        best_improvement = improvement
                        best_split = {
                            'feat': feat,
                            'val': split_val,
                            'left_tier': best_left_tier,
                            'right_tier': best_right_tier,
                        }

            if best_split and best_split['left_tier'] != best_split['right_tier']:
                self._eval_tree[eval_name] = best_split

    def solve(self, query: str, eval_name: str, candidate_models: list) -> str:
        self._load()

        if eval_name in self._eval_tree:
            tree = self._eval_tree[eval_name]
            feats = self._extract_features(query)
            val = feats.get(tree['feat'], 0)

            if val <= tree['val']:
                tier = tree['left_tier']
            else:
                tier = tree['right_tier']

            if tier in candidate_models:
                return tier

        best = self._eval_best.get(eval_name, "mid")
        return best if best in candidate_models else "mid"
