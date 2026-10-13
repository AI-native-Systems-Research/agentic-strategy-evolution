import pandas as pd
import numpy as np
import os
import re
from collections import Counter
import math

class Solution:
    def __init__(self):
        self._loaded = False

    def _tokenize(self, text):
        return re.findall(r'[a-zA-Z]{2,}', text.lower())

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

        self._tier_avg_cost = {}
        for tier, model in self._tier_map.items():
            if model in cost_cols:
                self._tier_avg_cost[tier] = df[cost_cols[model]].mean()

        # Per-eval best tier
        self._eval_best = {}
        self._eval_tier_acc = {}
        for eval_name in df['eval_name'].unique():
            edf = df[df['eval_name'] == eval_name]
            best_score = float('-inf')
            best_tier = "mid"
            tier_acc = {}
            for tier, model in self._tier_map.items():
                if model in model_cols and model in cost_cols:
                    acc = edf[model].mean()
                    cost = edf[cost_cols[model]].mean()
                    score = acc - 150.0 * cost
                    tier_acc[tier] = acc
                    if score > best_score:
                        best_score = score
                        best_tier = tier
            self._eval_best[eval_name] = best_tier
            self._eval_tier_acc[eval_name] = tier_acc

        # Build per-eval KNN: TF-IDF matrix + labels
        self._eval_knn = {}

        # Build global vocabulary with IDF
        doc_freq = Counter()
        n_docs = len(df)
        for _, row in df.iterrows():
            tokens = set(self._tokenize(str(row.get('prompt', ''))))
            doc_freq.update(tokens)

        # Keep top words by document frequency (at least 3 docs, at most 80% of docs)
        min_df = 3
        max_df = int(0.8 * n_docs)
        vocab = {w: i for i, (w, count) in enumerate(
            sorted([(w, c) for w, c in doc_freq.items() if min_df <= c <= max_df],
                   key=lambda x: -x[1])[:5000]
        )}
        idf = {}
        for w, idx in vocab.items():
            idf[w] = math.log(n_docs / (doc_freq[w] + 1))

        self._vocab = vocab
        self._idf = idf

        for eval_name in df['eval_name'].unique():
            edf = df[df['eval_name'] == eval_name]
            if len(edf) < 5:
                continue

            # Build TF-IDF matrix for this eval's prompts
            n = len(edf)
            tfidf_matrix = np.zeros((n, len(vocab)))
            norms = np.zeros(n)

            tier_correctness = {tier: [] for tier in self._tier_map}

            for i, (_, row) in enumerate(edf.iterrows()):
                tokens = self._tokenize(str(row.get('prompt', '')))
                tf = Counter(tokens)
                max_tf = max(tf.values()) if tf else 1

                for word, count in tf.items():
                    if word in vocab:
                        idx = vocab[word]
                        tfidf_matrix[i, idx] = (0.5 + 0.5 * count / max_tf) * idf.get(word, 0)

                norm = np.linalg.norm(tfidf_matrix[i])
                if norm > 0:
                    tfidf_matrix[i] /= norm
                    norms[i] = norm

                for tier, model in self._tier_map.items():
                    if model in model_cols:
                        tier_correctness[tier].append(row.get(model, 0))

            self._eval_knn[eval_name] = {
                'tfidf': tfidf_matrix,
                'tier_correct': {t: np.array(v) for t, v in tier_correctness.items()},
                'n': n,
            }

    def _query_to_tfidf(self, query):
        tokens = self._tokenize(str(query))
        tf = Counter(tokens)
        max_tf = max(tf.values()) if tf else 1

        vec = np.zeros(len(self._vocab))
        for word, count in tf.items():
            if word in self._vocab:
                idx = self._vocab[word]
                vec[idx] = (0.5 + 0.5 * count / max_tf) * self._idf.get(word, 0)

        norm = np.linalg.norm(vec)
        if norm > 0:
            vec /= norm
        return vec

    def solve(self, query: str, eval_name: str, candidate_models: list) -> str:
        self._load()

        knn_data = self._eval_knn.get(eval_name)

        if knn_data is not None and knn_data['n'] >= 5:
            query_vec = self._query_to_tfidf(query)

            # Cosine similarity
            similarities = knn_data['tfidf'] @ query_vec

            # Get top-k neighbors
            k = min(15, knn_data['n'])
            top_k_idx = np.argpartition(similarities, -k)[-k:]

            # Weighted vote
            best_tier = None
            best_expected = float('-inf')

            for tier in candidate_models:
                if tier not in knn_data['tier_correct']:
                    continue

                # Weighted accuracy among neighbors
                weights = similarities[top_k_idx]
                weights = np.maximum(weights, 0)  # only positive similarities
                total_weight = weights.sum()

                if total_weight > 0:
                    correctness = knn_data['tier_correct'][tier][top_k_idx]
                    p_correct = (weights * correctness).sum() / total_weight
                else:
                    p_correct = self._eval_tier_acc.get(eval_name, {}).get(tier, 0.5)

                cost = self._tier_avg_cost.get(tier, 0)
                expected = p_correct - 150.0 * cost

                if expected > best_expected:
                    best_expected = expected
                    best_tier = tier

            if best_tier:
                return best_tier

        # Fallback
        best = self._eval_best.get(eval_name, "mid")
        return best if best in candidate_models else "mid"
