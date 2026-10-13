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

        tier_order = ["cheap", "mid", "expensive"]

        def get_optimal_tier(row):
            for tier in tier_order:
                model = self._tier_map[tier]
                if model in model_cols and row.get(model, 0) == 1.0:
                    return tier
            return "cheap"

        df['optimal_tier'] = df.apply(get_optimal_tier, axis=1)

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

        # Try per-eval classifiers with sklearn
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.linear_model import LogisticRegression
            from sklearn.calibration import CalibratedClassifierCV

            self._eval_models = {}
            self._eval_vectorizers = {}
            self._eval_classes = {}

            for eval_name in df['eval_name'].unique():
                edf = df[df['eval_name'] == eval_name]
                if len(edf) < 20:
                    continue

                prompts = edf['prompt'].fillna('').astype(str).tolist()
                labels = edf['optimal_tier'].tolist()

                # Skip if only one class
                unique_labels = list(set(labels))
                if len(unique_labels) <= 1:
                    continue

                tfidf = TfidfVectorizer(
                    max_features=3000,
                    ngram_range=(1, 2),
                    sublinear_tf=True,
                    min_df=1,
                )
                X = tfidf.fit_transform(prompts)

                clf = LogisticRegression(
                    C=1.0,
                    max_iter=1000,
                    random_state=42,
                    multi_class='multinomial',
                )
                clf.fit(X, labels)

                self._eval_vectorizers[eval_name] = tfidf
                self._eval_models[eval_name] = clf
                self._eval_classes[eval_name] = unique_labels

            # Also build global model
            prompts = df['prompt'].fillna('').astype(str).tolist()
            eval_names = df['eval_name'].fillna('').astype(str).tolist()
            texts = [f"EVAL_{en} {p}" for en, p in zip(eval_names, prompts)]
            labels = df['optimal_tier'].tolist()

            self._global_tfidf = TfidfVectorizer(
                max_features=10000,
                ngram_range=(1, 2),
                sublinear_tf=True,
                min_df=2,
            )
            X = self._global_tfidf.fit_transform(texts)

            self._global_clf = LogisticRegression(
                C=1.0,
                max_iter=1000,
                random_state=42,
                multi_class='multinomial',
            )
            self._global_clf.fit(X, labels)

            self._use_ml = True

            # Store cost info for cost-aware decisions
            self._tier_avg_cost = {}
            for tier, model in self._tier_map.items():
                if model in cost_cols:
                    self._tier_avg_cost[tier] = df[cost_cols[model]].mean()

            print(f"ML initialized: {len(self._eval_models)} per-eval models", file=sys.stderr)

        except Exception as e:
            print(f"ML failed: {e}", file=sys.stderr)
            self._use_ml = False

    def solve(self, query: str, eval_name: str, candidate_models: list) -> str:
        self._load()

        if self._use_ml:
            try:
                # Use per-eval model if available
                if eval_name in self._eval_models:
                    tfidf = self._eval_vectorizers[eval_name]
                    clf = self._eval_models[eval_name]
                    X = tfidf.transform([str(query)])
                    probs = clf.predict_proba(X)[0]
                    classes = clf.classes_

                    # Cost-aware decision
                    best_tier = None
                    best_expected_score = float('-inf')
                    for i, cls in enumerate(classes):
                        if cls in candidate_models:
                            prob = probs[i]
                            cost = self._tier_avg_cost.get(cls, 0)
                            expected_score = prob - 150.0 * cost
                            if expected_score > best_expected_score:
                                best_expected_score = expected_score
                                best_tier = cls

                    if best_tier:
                        return best_tier

                # Fallback to global model
                text = f"EVAL_{eval_name} {query}"
                X = self._global_tfidf.transform([text])
                probs = self._global_clf.predict_proba(X)[0]
                classes = self._global_clf.classes_

                best_tier = None
                best_expected_score = float('-inf')
                for i, cls in enumerate(classes):
                    if cls in candidate_models:
                        prob = probs[i]
                        cost = self._tier_avg_cost.get(cls, 0)
                        expected_score = prob - 150.0 * cost
                        if expected_score > best_expected_score:
                            best_expected_score = expected_score
                            best_tier = cls

                if best_tier:
                    return best_tier

            except Exception as e:
                pass

        best = self._eval_best.get(eval_name, "mid")
        return best if best in candidate_models else "mid"
