import pandas as pd
import numpy as np
import os
import re
from collections import Counter
import math

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
        self._eval_tier_cost = {}
        for eval_name in df['eval_name'].unique():
            edf = df[df['eval_name'] == eval_name]
            best_score = float('-inf')
            best_tier = "mid"
            costs = {}
            for tier, model in self._tier_map.items():
                if model in model_cols and model in cost_cols:
                    acc = edf[model].mean()
                    cost = edf[cost_cols[model]].mean()
                    costs[tier] = cost
                    score = acc - 150.0 * cost
                    if score > best_score:
                        best_score = score
                        best_tier = tier
            self._eval_best[eval_name] = best_tier
            self._eval_tier_cost[eval_name] = costs

        self._tier_avg_cost = {}
        for tier, model in self._tier_map.items():
            if model in cost_cols:
                self._tier_avg_cost[tier] = df[cost_cols[model]].mean()

        # Build TF-IDF from scratch and train logistic regression per tier
        # Step 1: Build vocabulary
        prompts = df['prompt'].fillna('').astype(str).tolist()
        eval_names = df['eval_name'].fillna('').astype(str).tolist()

        doc_freq = Counter()
        n_docs = len(prompts)

        tokenized = []
        for p, en in zip(prompts, eval_names):
            tokens = re.findall(r'[a-zA-Z]{2,}', p.lower())
            tokens.append(f'__eval_{en}__')
            tokenized.append(tokens)
            doc_freq.update(set(tokens))

        # Filter vocabulary
        min_df = 3
        max_df = int(0.8 * n_docs)
        vocab_items = [(w, c) for w, c in doc_freq.items()
                       if min_df <= c <= max_df or w.startswith('__eval_')]
        vocab_items.sort(key=lambda x: -x[1])
        vocab = {w: i for i, (w, _) in enumerate(vocab_items[:8000])}
        vocab_size = len(vocab)

        if vocab_size == 0:
            return

        # IDF
        idf = np.zeros(vocab_size)
        for w, idx in vocab.items():
            idf[idx] = math.log(n_docs / (doc_freq.get(w, 0) + 1)) + 1

        self._vocab = vocab
        self._idf = idf

        # Step 2: Build TF-IDF matrix
        X = np.zeros((n_docs, vocab_size))
        for i, tokens in enumerate(tokenized):
            tf = Counter(tokens)
            for w, count in tf.items():
                if w in vocab:
                    idx = vocab[w]
                    X[i, idx] = (1 + math.log(count)) * idf[idx]

            # L2 normalize
            norm = np.linalg.norm(X[i])
            if norm > 0:
                X[i] /= norm

        # Step 3: Train per-tier logistic regression
        # Binary: P(model correct | features) for each tier
        self._weights = {}
        self._biases = {}

        for tier, model in self._tier_map.items():
            if model not in model_cols:
                continue

            y = df[model].fillna(0).values.astype(float)

            # Logistic regression via gradient descent
            w = np.zeros(vocab_size)
            b = 0.0
            lr = 0.1
            reg = 0.01  # L2 regularization
            n_epochs = 50

            for epoch in range(n_epochs):
                logits = X @ w + b
                logits = np.clip(logits, -30, 30)
                probs = 1.0 / (1.0 + np.exp(-logits))

                # Gradient
                error = probs - y
                grad_w = (X.T @ error) / n_docs + reg * w
                grad_b = error.mean()

                w -= lr * grad_w
                b -= lr * grad_b

                # Decay learning rate
                if (epoch + 1) % 20 == 0:
                    lr *= 0.5

            self._weights[tier] = w
            self._biases[tier] = b

        self._has_model = True

    def _query_to_features(self, query, eval_name):
        tokens = re.findall(r'[a-zA-Z]{2,}', str(query).lower())
        tokens.append(f'__eval_{eval_name}__')

        vec = np.zeros(len(self._vocab))
        tf = Counter(tokens)
        for w, count in tf.items():
            if w in self._vocab:
                idx = self._vocab[w]
                vec[idx] = (1 + math.log(count)) * self._idf[idx]

        norm = np.linalg.norm(vec)
        if norm > 0:
            vec /= norm
        return vec

    def _predict_prob(self, tier, features):
        if tier not in self._weights:
            return 0.5
        logit = features @ self._weights[tier] + self._biases[tier]
        logit = np.clip(logit, -30, 30)
        return 1.0 / (1.0 + np.exp(-logit))

    def solve(self, query: str, eval_name: str, candidate_models: list) -> str:
        self._load()

        if hasattr(self, '_has_model') and self._has_model:
            features = self._query_to_features(query, eval_name)
            costs = self._eval_tier_cost.get(eval_name, self._tier_avg_cost)

            best_tier = None
            best_expected = float('-inf')
            for tier in candidate_models:
                p_correct = self._predict_prob(tier, features)
                cost = costs.get(tier, self._tier_avg_cost.get(tier, 0))
                expected = p_correct - 150.0 * cost
                if expected > best_expected:
                    best_expected = expected
                    best_tier = tier

            if best_tier:
                return best_tier

        best = self._eval_best.get(eval_name, "mid")
        return best if best in candidate_models else "mid"
