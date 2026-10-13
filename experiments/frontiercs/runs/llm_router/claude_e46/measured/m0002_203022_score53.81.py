import pandas as pd
import numpy as np
import os
import sys
import re
from collections import Counter

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
            self._fallback = "cheap"
            return

        self._df = df
        all_cols = df.columns.tolist()

        model_cols = []
        cost_cols = {}
        for c in all_cols:
            if '|total_cost' in c:
                model_name = c.replace('|total_cost', '')
                cost_cols[model_name] = c
            elif c not in ['sample_id', 'prompt', 'eval_name', 'oracle_model_to_route_to'] and '|' not in c:
                model_cols.append(c)

        self._tier_map = {
            "cheap": "mistralai/mistral-7b-chat",
            "mid": "mistralai/mixtral-8x7b-chat",
            "expensive": "gpt-4-1106-preview",
        }
        self._reverse_tier = {v: k for k, v in self._tier_map.items()}

        # For each row, determine the optimal tier (cheapest correct, or cheapest if all wrong)
        tier_order = ["cheap", "mid", "expensive"]

        def get_optimal_tier(row):
            for tier in tier_order:
                model = self._tier_map[tier]
                if model in model_cols and row.get(model, 0) == 1.0:
                    return tier
            return "cheap"  # all wrong -> minimize cost

        df['optimal_tier'] = df.apply(get_optimal_tier, axis=1)

        # Compute per-eval stats
        self._eval_tier_stats = {}
        self._eval_optimal_dist = {}
        for eval_name in df['eval_name'].unique():
            edf = df[df['eval_name'] == eval_name]
            tier_stats = {}
            for tier, model in self._tier_map.items():
                if model in model_cols and model in cost_cols:
                    acc = edf[model].mean()
                    cost = edf[cost_cols[model]].mean()
                    score = acc - 150.0 * cost
                    tier_stats[tier] = {'acc': acc, 'cost': cost, 'score': score}
            self._eval_tier_stats[eval_name] = tier_stats
            self._eval_optimal_dist[eval_name] = edf['optimal_tier'].value_counts(normalize=True).to_dict()

        # Compute features for the reference data for learning
        # We'll use a simple approach: learn per-eval query-length based thresholds
        self._eval_length_model = {}
        for eval_name in df['eval_name'].unique():
            edf = df[df['eval_name'] == eval_name].copy()
            edf['qlen'] = edf['prompt'].str.len()

            # For this eval, check if query length separates cheap-correct from cheap-wrong
            cheap_model = self._tier_map["cheap"]
            if cheap_model not in model_cols:
                continue

            cheap_correct = edf[edf[cheap_model] == 1.0]['qlen']
            cheap_wrong = edf[edf[cheap_model] == 0.0]['qlen']

            if len(cheap_correct) == 0 or len(cheap_wrong) == 0:
                continue

            # Store basic stats for length-based routing
            self._eval_length_model[eval_name] = {
                'correct_median': cheap_correct.median(),
                'wrong_median': cheap_wrong.median(),
                'correct_mean': cheap_correct.mean(),
                'wrong_mean': cheap_wrong.mean(),
            }

        # Try to use sklearn for a proper classifier
        try:
            from sklearn.ensemble import GradientBoostingClassifier
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.preprocessing import LabelEncoder
            import hashlib

            self._use_ml = True

            # Build features
            features = []
            labels = []
            for _, row in df.iterrows():
                prompt = str(row.get('prompt', ''))
                en = str(row.get('eval_name', ''))
                feat = self._extract_features(prompt, en)
                features.append(feat)
                labels.append(row['optimal_tier'])

            X = np.array(features)
            y = np.array(labels)

            self._le = LabelEncoder()
            y_enc = self._le.fit_transform(y)

            self._clf = GradientBoostingClassifier(
                n_estimators=200,
                max_depth=4,
                learning_rate=0.1,
                random_state=42
            )
            self._clf.fit(X, y_enc)

        except Exception as e:
            print(f"ML failed: {e}", file=sys.stderr)
            self._use_ml = False

    def _extract_features(self, prompt, eval_name):
        """Extract numerical features from query text."""
        prompt = str(prompt)
        features = []

        # Length features
        features.append(len(prompt))
        features.append(len(prompt.split()))
        features.append(len(prompt.split('\n')))

        # Character composition
        alpha = sum(c.isalpha() for c in prompt)
        digit = sum(c.isdigit() for c in prompt)
        space = sum(c.isspace() for c in prompt)
        total = max(len(prompt), 1)
        features.append(alpha / total)
        features.append(digit / total)
        features.append(space / total)

        # Punctuation counts
        features.append(prompt.count('?'))
        features.append(prompt.count('.'))
        features.append(prompt.count(','))
        features.append(prompt.count(':'))
        features.append(prompt.count(';'))
        features.append(prompt.count('('))
        features.append(prompt.count(')'))

        # Code indicators
        features.append(1 if 'def ' in prompt else 0)
        features.append(1 if 'class ' in prompt else 0)
        features.append(1 if 'import ' in prompt else 0)
        features.append(1 if 'return ' in prompt else 0)
        features.append(1 if '```' in prompt else 0)
        features.append(prompt.count('    '))  # indentation

        # MCQ indicators
        features.append(1 if '\nA)' in prompt or '\nA.' in prompt else 0)
        features.append(1 if '\nB)' in prompt or '\nB.' in prompt else 0)
        features.append(1 if '\nC)' in prompt or '\nC.' in prompt else 0)
        features.append(1 if '\nD)' in prompt or '\nD.' in prompt else 0)
        features.append(1 if '\nE)' in prompt or '\nE.' in prompt else 0)

        # Math indicators
        features.append(1 if '=' in prompt else 0)
        features.append(1 if '+' in prompt else 0)
        features.append(prompt.count('*'))

        # Eval name encoding (hash-based features)
        eval_hash = hash(eval_name) % 100
        features.append(eval_hash)

        # Average word length
        words = prompt.split()
        if words:
            features.append(np.mean([len(w) for w in words]))
            features.append(max(len(w) for w in words))
        else:
            features.append(0)
            features.append(0)

        # Unique word ratio
        if words:
            features.append(len(set(words)) / len(words))
        else:
            features.append(0)

        # Sentence count (rough)
        features.append(len(re.split(r'[.!?]+', prompt)))

        # Uppercase ratio
        upper = sum(c.isupper() for c in prompt)
        features.append(upper / total)

        return features

    def solve(self, query: str, eval_name: str, candidate_models: list) -> str:
        self._load()

        if hasattr(self, '_use_ml') and self._use_ml:
            try:
                feat = self._extract_features(query, eval_name)
                X = np.array([feat])
                pred = self._clf.predict(X)[0]
                tier = self._le.inverse_transform([pred])[0]
                if tier in candidate_models:
                    return tier
            except:
                pass

        # Fallback: per-eval best tier
        stats = self._eval_tier_stats.get(eval_name, {})
        if not stats:
            return "cheap" if "cheap" in candidate_models else candidate_models[0]

        best_tier = max(candidate_models, key=lambda t: stats.get(t, {}).get('score', float('-inf')))
        return best_tier
