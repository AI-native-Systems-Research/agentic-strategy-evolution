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
        self._has_knn = False

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

        # Base: per-eval average P(correct) and cost for each tier
        self._eval_tier_prob = {}
        self._eval_tier_cost = {}
        self._eval_best = {}

        for eval_name in df['eval_name'].unique():
            edf = df[df['eval_name'] == eval_name]
            probs = {}
            costs = {}
            best_score = float('-inf')
            best_tier = "mid"
            for tier, model in self._tier_map.items():
                if model in model_cols and model in cost_cols:
                    acc = edf[model].mean()
                    cost = edf[cost_cols[model]].mean()
                    probs[tier] = acc
                    costs[tier] = cost
                    score = acc - 150.0 * cost
                    if score > best_score:
                        best_score = score
                        best_tier = tier
            self._eval_tier_prob[eval_name] = probs
            self._eval_tier_cost[eval_name] = costs
            self._eval_best[eval_name] = best_tier

        self._tier_avg_cost = {}
        for tier, model in self._tier_map.items():
            if model in cost_cols:
                self._tier_avg_cost[tier] = df[cost_cols[model]].mean()

        # Build per-eval KNN for text-based adjustment
        # Only for eval_names where the top 2 tiers are close
        # (where per-query routing would matter most)
        self._eval_knn = {}

        for eval_name in df['eval_name'].unique():
            edf = df[df['eval_name'] == eval_name]
            if len(edf) < 50:
                continue

            # Check if top 2 tiers are close in score
            scores = {}
            for tier, model in self._tier_map.items():
                if model in model_cols and model in cost_cols:
                    acc = edf[model].mean()
                    cost = edf[cost_cols[model]].mean()
                    scores[tier] = acc - 150.0 * cost

            sorted_tiers = sorted(scores.items(), key=lambda x: -x[1])
            if len(sorted_tiers) < 2:
                continue

            score_gap = sorted_tiers[0][1] - sorted_tiers[1][1]
            if score_gap > 0.1:
                # Big gap - per-eval routing is sufficient
                continue

            # Build simple word-frequency features for KNN
            # Use top-100 most informative words per eval
            prompts = edf['prompt'].fillna('').astype(str).tolist()

            # Build vocabulary for this eval
            doc_freq = Counter()
            tokenized = []
            for p in prompts:
                tokens = set(re.findall(r'[a-z]{3,}', p.lower()))
                tokenized.append(tokens)
                doc_freq.update(tokens)

            n = len(prompts)
            vocab = [w for w, c in doc_freq.most_common(500)
                     if 3 <= c <= int(0.8 * n)][:200]
            word_to_idx = {w: i for i, w in enumerate(vocab)}

            if len(vocab) < 10:
                continue

            # Build feature matrix (binary)
            X = np.zeros((n, len(vocab)))
            for i, tokens in enumerate(tokenized):
                for t in tokens:
                    if t in word_to_idx:
                        X[i, word_to_idx[t]] = 1

            # Normalize
            norms = np.linalg.norm(X, axis=1, keepdims=True)
            norms[norms == 0] = 1
            X = X / norms

            # Store tier correctness
            tier_correct = {}
            for tier, model in self._tier_map.items():
                if model in model_cols:
                    tier_correct[tier] = edf[model].fillna(0).values

            tier_cost = {}
            for tier, model in self._tier_map.items():
                if model in cost_cols:
                    tier_cost[tier] = edf[cost_cols[model]].fillna(0).values

            self._eval_knn[eval_name] = {
                'X': X,
                'word_to_idx': word_to_idx,
                'tier_correct': tier_correct,
                'tier_cost': tier_cost,
                'n': n,
            }

        self._has_knn = True

    def _query_features(self, query, word_to_idx):
        tokens = set(re.findall(r'[a-z]{3,}', str(query).lower()))
        vec = np.zeros(len(word_to_idx))
        for t in tokens:
            if t in word_to_idx:
                vec[word_to_idx[t]] = 1
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec /= norm
        return vec

    def solve(self, query: str, eval_name: str, candidate_models: list) -> str:
        self._load()

        # Base prediction: per-eval best tier
        base_probs = self._eval_tier_prob.get(eval_name, {})
        base_costs = self._eval_tier_cost.get(eval_name, self._tier_avg_cost)

        if not base_probs:
            return "mid" if "mid" in candidate_models else candidate_models[0]

        # Try KNN adjustment if available
        if self._has_knn and eval_name in self._eval_knn:
            knn = self._eval_knn[eval_name]
            q_feat = self._query_features(query, knn['word_to_idx'])

            # Cosine similarity
            sims = knn['X'] @ q_feat
            k = min(20, knn['n'])
            top_idx = np.argpartition(sims, -k)[-k:]

            # Blend: 70% prior (per-eval avg) + 30% KNN
            alpha = 0.3
            best_tier = None
            best_expected = float('-inf')

            for tier in candidate_models:
                # Base probability
                p_base = base_probs.get(tier, 0.5)

                # KNN adjustment
                if tier in knn['tier_correct']:
                    weights = np.maximum(sims[top_idx], 0)
                    total_w = weights.sum()
                    if total_w > 0:
                        p_knn = (weights * knn['tier_correct'][tier][top_idx]).sum() / total_w
                    else:
                        p_knn = p_base
                else:
                    p_knn = p_base

                p_final = (1 - alpha) * p_base + alpha * p_knn
                cost = base_costs.get(tier, self._tier_avg_cost.get(tier, 0))
                expected = p_final - 150.0 * cost

                if expected > best_expected:
                    best_expected = expected
                    best_tier = tier

            if best_tier:
                return best_tier

        # Pure per-eval fallback
        best_tier = None
        best_expected = float('-inf')
        for tier in candidate_models:
            p = base_probs.get(tier, 0.5)
            cost = base_costs.get(tier, self._tier_avg_cost.get(tier, 0))
            expected = p - 150.0 * cost
            if expected > best_expected:
                best_expected = expected
                best_tier = tier

        return best_tier if best_tier else "mid"
