import pandas as pd
import numpy as np
import os
import sys

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

        self._tier_map = {
            "cheap": "mistralai/mistral-7b-chat",
            "mid": "mistralai/mixtral-8x7b-chat",
            "expensive": "gpt-4-1106-preview",
        }

        # Per-eval average costs
        self._tier_avg_cost = {}
        for tier, model in self._tier_map.items():
            if model in cost_cols:
                self._tier_avg_cost[tier] = df[cost_cols[model]].mean()

        # Per-eval best tier as fallback
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

        # Train per-tier correctness classifiers
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.linear_model import LogisticRegression

            prompts = df['prompt'].fillna('').astype(str).tolist()
            eval_names = df['eval_name'].fillna('').astype(str).tolist()
            texts = [f"EVALCAT_{en} " + p for en, p in zip(eval_names, prompts)]

            self._tfidf = TfidfVectorizer(
                max_features=10000,
                ngram_range=(1, 2),
                sublinear_tf=True,
                min_df=2,
            )
            X = self._tfidf.fit_transform(texts)

            # Train a binary classifier per tier
            self._tier_clfs = {}
            for tier, model in self._tier_map.items():
                if model in model_cols:
                    y = df[model].fillna(0).values.astype(int)
                    clf = LogisticRegression(
                        C=1.0, max_iter=1000, random_state=42
                    )
                    clf.fit(X, y)
                    self._tier_clfs[tier] = clf

                    train_pred = clf.predict_proba(X)[:, 1]
                    print(f"Tier {tier}: avg P(correct)={train_pred.mean():.4f}, actual={y.mean():.4f}", file=sys.stderr)

            # Per-eval cost dict
            self._eval_tier_cost = {}
            for eval_name in df['eval_name'].unique():
                edf = df[df['eval_name'] == eval_name]
                costs = {}
                for tier, model in self._tier_map.items():
                    if model in cost_cols:
                        costs[tier] = edf[cost_cols[model]].mean()
                self._eval_tier_cost[eval_name] = costs

            self._use_ml = True
            print("Per-tier classifiers initialized", file=sys.stderr)

        except Exception as e:
            print(f"ML failed: {e}", file=sys.stderr)
            self._use_ml = False

    def solve(self, query: str, eval_name: str, candidate_models: list) -> str:
        self._load()

        if self._use_ml:
            try:
                text = f"EVALCAT_{eval_name} " + str(query)
                X = self._tfidf.transform([text])

                costs = self._eval_tier_cost.get(eval_name, self._tier_avg_cost)

                best_tier = None
                best_expected = float('-inf')
                for tier in candidate_models:
                    if tier in self._tier_clfs:
                        prob = self._tier_clfs[tier].predict_proba(X)[0, 1]
                        cost = costs.get(tier, self._tier_avg_cost.get(tier, 0))
                        expected = prob - 150.0 * cost
                        if expected > best_expected:
                            best_expected = expected
                            best_tier = tier

                if best_tier:
                    return best_tier
            except:
                pass

        best = self._eval_best.get(eval_name, "mid")
        return best if best in candidate_models else "mid"
