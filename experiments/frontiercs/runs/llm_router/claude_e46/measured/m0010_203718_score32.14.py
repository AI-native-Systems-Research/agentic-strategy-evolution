import pandas as pd
import numpy as np
import os
import sys
import itertools

class Solution:
    def __init__(self):
        self._loaded = False

    def _load(self):
        if self._loaded:
            return
        self._loaded = True
        self._use_ml = False

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

        # Only consider models that have both correctness and cost columns
        valid_models = [m for m in model_cols if m in cost_cols]

        # Compute avg cost per model
        avg_costs = {m: df[cost_cols[m]].mean() for m in valid_models}

        # Sort by cost
        sorted_models = sorted(valid_models, key=lambda m: avg_costs[m])
        print(f"Models by cost: {[(m, avg_costs[m]) for m in sorted_models]}", file=sys.stderr)

        # Try to find the best 3-model mapping
        # Group models into 3 cost tiers naturally
        # cheap: lowest cost group, mid: middle, expensive: highest
        # Try all combinations of 3 models and find best oracle score
        best_mapping = None
        best_score = float('-inf')

        # For efficiency, only consider models that are the cheapest, a mid one, and the most expensive
        # But let's try all triples to be thorough (only 11 C 3 * 6 = 990 combos)
        for combo in itertools.combinations(valid_models, 3):
            # Try all 6 orderings (assignments to cheap/mid/expensive)
            for perm in itertools.permutations(combo):
                cheap_m, mid_m, exp_m = perm

                # Must have cheap < mid < expensive in cost
                if avg_costs[cheap_m] >= avg_costs[mid_m] or avg_costs[mid_m] >= avg_costs[exp_m]:
                    continue

                # Compute oracle score for this mapping
                total_score = 0
                n = len(df)
                for _, row in df.iterrows():
                    # Oracle: cheapest correct
                    best_q_score = float('-inf')
                    for tier_model, tier_cost_col in [(cheap_m, cost_cols[cheap_m]),
                                                       (mid_m, cost_cols[mid_m]),
                                                       (exp_m, cost_cols[exp_m])]:
                        correct = row.get(tier_model, 0)
                        cost = row.get(tier_cost_col, 0)
                        q_score = correct - 150 * cost
                        if q_score > best_q_score:
                            best_q_score = q_score

                    total_score += best_q_score

                avg_score = total_score / n
                if avg_score > best_score:
                    best_score = avg_score
                    best_mapping = perm

        if best_mapping:
            self._tier_map = {
                "cheap": best_mapping[0],
                "mid": best_mapping[1],
                "expensive": best_mapping[2],
            }
            print(f"Best mapping: {self._tier_map}", file=sys.stderr)
            print(f"Best training oracle score: {best_score:.6f}", file=sys.stderr)
        else:
            self._tier_map = {
                "cheap": "mistralai/mistral-7b-chat",
                "mid": "mistralai/mixtral-8x7b-chat",
                "expensive": "gpt-4-1106-preview",
            }

        # Per-eval best tier
        self._eval_best = {}
        for eval_name in df['eval_name'].unique():
            edf = df[df['eval_name'] == eval_name]
            best_tier_score = float('-inf')
            best_tier = "mid"
            for tier, model in self._tier_map.items():
                if model in valid_models:
                    acc = edf[model].mean()
                    cost = edf[cost_cols[model]].mean()
                    score = acc - 150.0 * cost
                    if score > best_tier_score:
                        best_tier_score = score
                        best_tier = tier
            self._eval_best[eval_name] = best_tier

        # Try ML
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.linear_model import LogisticRegression

            self._tier_avg_cost = {}
            for tier, model in self._tier_map.items():
                if model in cost_cols:
                    self._tier_avg_cost[tier] = df[cost_cols[model]].mean()

            # Train correctness classifiers per tier
            prompts = df['prompt'].fillna('').astype(str).tolist()
            evals = df['eval_name'].fillna('').astype(str).tolist()
            texts = [f"EVALCAT_{en} {p}" for en, p in zip(evals, prompts)]

            self._tfidf = TfidfVectorizer(
                max_features=10000, ngram_range=(1, 2),
                sublinear_tf=True, min_df=2,
            )
            X = self._tfidf.fit_transform(texts)

            self._tier_clfs = {}
            for tier, model in self._tier_map.items():
                if model in model_cols:
                    y = df[model].fillna(0).values.astype(int)
                    clf = LogisticRegression(C=1.0, max_iter=1000, random_state=42)
                    clf.fit(X, y)
                    self._tier_clfs[tier] = clf

            self._eval_tier_cost = {}
            for eval_name in df['eval_name'].unique():
                edf = df[df['eval_name'] == eval_name]
                costs = {}
                for tier, model in self._tier_map.items():
                    if model in cost_cols:
                        costs[tier] = edf[cost_cols[model]].mean()
                self._eval_tier_cost[eval_name] = costs

            self._use_ml = True

        except Exception as e:
            print(f"ML failed: {e}", file=sys.stderr)

    def solve(self, query: str, eval_name: str, candidate_models: list) -> str:
        self._load()

        if self._use_ml:
            try:
                text = f"EVALCAT_{eval_name} {str(query)}"
                X = self._tfidf.transform([text])
                costs = self._eval_tier_cost.get(eval_name, self._tier_avg_cost)

                best_tier = None
                best_exp = float('-inf')
                for tier in candidate_models:
                    if tier in self._tier_clfs:
                        prob = self._tier_clfs[tier].predict_proba(X)[0]
                        p_correct = prob[1] if len(prob) > 1 else prob[0]
                        cost = costs.get(tier, self._tier_avg_cost.get(tier, 0))
                        exp_score = p_correct - 150.0 * cost
                        if exp_score > best_exp:
                            best_exp = exp_score
                            best_tier = tier
                if best_tier:
                    return best_tier
            except:
                pass

        best = self._eval_best.get(eval_name, "mid")
        return best if best in candidate_models else "mid"
