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
        self._use_knn = False

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

        tier_order = ["cheap", "mid", "expensive"]

        def get_optimal_tier(row):
            for tier in tier_order:
                model = self._tier_map[tier]
                if model in model_cols and row.get(model, 0) == 1.0:
                    return tier
            return "cheap"

        df['optimal_tier'] = df.apply(get_optimal_tier, axis=1)

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

        # Try KNN with TF-IDF
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.neighbors import NearestNeighbors

            prompts = df['prompt'].fillna('').astype(str).tolist()
            eval_names = df['eval_name'].fillna('').astype(str).tolist()

            # Combine eval_name with prompt for TF-IDF
            texts = [f"EVAL_{en} {p}" for en, p in zip(eval_names, prompts)]

            self._tfidf = TfidfVectorizer(
                max_features=10000,
                ngram_range=(1, 2),
                sublinear_tf=True,
                min_df=1,
            )
            X = self._tfidf.fit_transform(texts)

            self._knn = NearestNeighbors(n_neighbors=15, metric='cosine', algorithm='brute')
            self._knn.fit(X)

            self._train_tiers = df['optimal_tier'].tolist()
            self._train_eval = eval_names

            # Also store per-query correctness for weighted voting
            self._train_correct = {}
            for tier, model in self._tier_map.items():
                if model in model_cols:
                    self._train_correct[tier] = df[model].tolist()

            self._train_costs = {}
            for tier, model in self._tier_map.items():
                if model in cost_cols:
                    self._train_costs[tier] = df[cost_cols[model]].tolist()

            self._use_knn = True
            print("KNN initialized successfully", file=sys.stderr)

        except Exception as e:
            print(f"KNN failed: {e}", file=sys.stderr)
            self._use_knn = False

    def solve(self, query: str, eval_name: str, candidate_models: list) -> str:
        self._load()

        if self._use_knn:
            try:
                text = f"EVAL_{eval_name} {query}"
                X = self._tfidf.transform([text])
                distances, indices = self._knn.kneighbors(X)

                # Weighted vote: for each neighbor, compute expected score for each tier
                tier_scores = {t: 0.0 for t in candidate_models}
                total_weight = 0.0

                for dist, idx in zip(distances[0], indices[0]):
                    weight = 1.0 / (dist + 1e-6)
                    total_weight += weight

                    for tier in candidate_models:
                        if tier in self._train_correct and tier in self._train_costs:
                            correct = self._train_correct[tier][idx]
                            cost = self._train_costs[tier][idx]
                            score = correct - 150.0 * cost
                            tier_scores[tier] += weight * score

                if total_weight > 0:
                    for t in tier_scores:
                        tier_scores[t] /= total_weight

                best = max(candidate_models, key=lambda t: tier_scores.get(t, float('-inf')))
                return best

            except Exception as e:
                pass

        # Fallback
        best = self._eval_best.get(eval_name, "mid")
        return best if best in candidate_models else "mid"
