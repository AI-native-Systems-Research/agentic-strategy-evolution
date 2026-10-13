import pandas as pd
import numpy as np
import os
import sys
import re
import hashlib

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
            self._use_ml = False
            return

        self._df = df
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

        # Per eval stats for fallback
        self._eval_tier_stats = {}
        for eval_name in df['eval_name'].unique():
            edf = df[df['eval_name'] == eval_name]
            tier_stats = {}
            for tier, model in self._tier_map.items():
                if model in model_cols and model in cost_cols:
                    acc = edf[model].mean()
                    cost = edf[cost_cols[model]].mean()
                    score = acc - 150.0 * cost
                    tier_stats[tier] = score
            self._eval_tier_stats[eval_name] = tier_stats

        # Try ML approach
        try:
            from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
            from sklearn.feature_extraction.text import TfidfVectorizer, HashingVectorizer
            from sklearn.preprocessing import LabelEncoder
            from sklearn.pipeline import Pipeline
            from scipy.sparse import hstack, csr_matrix

            # Use TF-IDF on query text + eval_name one-hot
            eval_names = df['eval_name'].unique().tolist()
            self._eval_name_list = eval_names
            eval_to_idx = {en: i for i, en in enumerate(eval_names)}

            prompts = df['prompt'].fillna('').astype(str).tolist()
            labels = df['optimal_tier'].tolist()

            # TF-IDF features
            self._tfidf = TfidfVectorizer(
                max_features=5000,
                ngram_range=(1, 2),
                sublinear_tf=True,
                min_df=2
            )
            X_tfidf = self._tfidf.fit_transform(prompts)

            # Eval name one-hot
            eval_onehot = np.zeros((len(df), len(eval_names)))
            for i, en in enumerate(df['eval_name']):
                if en in eval_to_idx:
                    eval_onehot[i, eval_to_idx[en]] = 1.0
            X_eval = csr_matrix(eval_onehot)

            # Numerical features
            num_feats = []
            for _, row in df.iterrows():
                prompt = str(row.get('prompt', ''))
                num_feats.append(self._num_features(prompt))
            X_num = csr_matrix(np.array(num_feats))

            X = hstack([X_tfidf, X_eval, X_num])

            self._le = LabelEncoder()
            y = self._le.fit_transform(labels)

            self._clf = GradientBoostingClassifier(
                n_estimators=300,
                max_depth=5,
                learning_rate=0.1,
                random_state=42,
                subsample=0.8,
            )
            self._clf.fit(X.toarray(), y)
            self._eval_to_idx = eval_to_idx
            self._use_ml = True

            # Print training accuracy
            train_pred = self._clf.predict(X.toarray())
            train_acc = (train_pred == y).mean()
            print(f"ML training accuracy: {train_acc:.4f}", file=sys.stderr)

        except Exception as e:
            print(f"ML failed: {e}", file=sys.stderr)
            self._use_ml = False

    def _num_features(self, prompt):
        prompt = str(prompt)
        total = max(len(prompt), 1)
        words = prompt.split()
        nwords = len(words)

        feats = [
            len(prompt),
            nwords,
            len(prompt.split('\n')),
            sum(c.isdigit() for c in prompt) / total,
            sum(c.isupper() for c in prompt) / total,
            prompt.count('?'),
            prompt.count('.'),
            prompt.count(','),
            1.0 if 'def ' in prompt else 0.0,
            1.0 if 'class ' in prompt else 0.0,
            1.0 if 'import ' in prompt else 0.0,
            1.0 if 'return ' in prompt else 0.0,
            1.0 if '```' in prompt else 0.0,
            prompt.count('    '),
            1.0 if re.search(r'\nA[).:]', prompt) else 0.0,
            1.0 if re.search(r'\nD[).:]', prompt) else 0.0,
            1.0 if '=' in prompt else 0.0,
            np.mean([len(w) for w in words]) if words else 0,
            len(set(words)) / nwords if nwords > 0 else 0,
        ]
        return feats

    def solve(self, query: str, eval_name: str, candidate_models: list) -> str:
        self._load()

        if self._use_ml:
            try:
                from scipy.sparse import hstack, csr_matrix

                X_tfidf = self._tfidf.transform([str(query)])

                eval_onehot = np.zeros((1, len(self._eval_name_list)))
                if eval_name in self._eval_to_idx:
                    eval_onehot[0, self._eval_to_idx[eval_name]] = 1.0
                X_eval = csr_matrix(eval_onehot)

                X_num = csr_matrix(np.array([self._num_features(query)]))

                X = hstack([X_tfidf, X_eval, X_num])
                pred = self._clf.predict(X.toarray())[0]
                tier = self._le.inverse_transform([pred])[0]
                if tier in candidate_models:
                    return tier
            except:
                pass

        # Fallback
        stats = self._eval_tier_stats.get(eval_name, {})
        if stats:
            return max(candidate_models, key=lambda t: stats.get(t, float('-inf')))
        return "cheap" if "cheap" in candidate_models else candidate_models[0]
