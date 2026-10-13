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
            self._sklearn_ok = False
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

        # Test sklearn by using it for routing
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression

        # This will raise if sklearn not available
        prompts = df['prompt'].fillna('').astype(str).tolist()
        evals = df['eval_name'].fillna('').astype(str).tolist()
        texts = [f"EVALCAT_{en} {p}" for en, p in zip(evals, prompts)]

        # Compute optimal tier
        tier_order = ["cheap", "mid", "expensive"]
        def get_opt(row):
            for t in tier_order:
                m = self._tier_map[t]
                if m in model_cols and row.get(m, 0) == 1.0:
                    return t
            return "cheap"
        labels = df.apply(get_opt, axis=1).tolist()

        self._tfidf = TfidfVectorizer(max_features=10000, ngram_range=(1, 2), sublinear_tf=True, min_df=2)
        X = self._tfidf.fit_transform(texts)

        self._clf = LogisticRegression(C=1.0, max_iter=1000, random_state=42, multi_class='multinomial')
        self._clf.fit(X, labels)
        self._sklearn_ok = True

    def solve(self, query: str, eval_name: str, candidate_models: list) -> str:
        self._load()

        if self._sklearn_ok:
            text = f"EVALCAT_{eval_name} {str(query)}"
            X = self._tfidf.transform([text])
            pred = self._clf.predict(X)[0]
            if pred in candidate_models:
                return pred

        best = self._eval_best.get(eval_name, "mid")
        return best if best in candidate_models else "mid"
