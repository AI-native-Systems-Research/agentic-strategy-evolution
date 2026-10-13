import pandas as pd
import numpy as np
import os
import re
from collections import Counter, defaultdict
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

        # Compute per-eval_name, per-tier stats
        self._eval_best = {}
        self._eval_tier_acc = {}
        self._tier_avg_cost = {}

        for tier, model in self._tier_map.items():
            if model in cost_cols:
                self._tier_avg_cost[tier] = df[cost_cols[model]].mean()

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

        # Build Naive Bayes classifier per tier (is model correct?)
        # For each tier, learn P(word | correct) and P(word | wrong) per eval_name
        self._nb_models = {}

        for tier, model in self._tier_map.items():
            if model not in model_cols:
                continue

            # Per eval_name NB model
            eval_nb = {}
            for eval_name in df['eval_name'].unique():
                edf = df[df['eval_name'] == eval_name]
                if len(edf) < 10:
                    continue

                correct_mask = edf[model] == 1.0
                wrong_mask = edf[model] == 0.0

                if correct_mask.sum() == 0 or wrong_mask.sum() == 0:
                    continue

                # Count words in correct vs wrong prompts
                correct_words = Counter()
                wrong_words = Counter()
                total_correct = 0
                total_wrong = 0

                for _, row in edf.iterrows():
                    tokens = self._tokenize(str(row.get('prompt', '')))
                    if row[model] == 1.0:
                        correct_words.update(tokens)
                        total_correct += len(tokens)
                    else:
                        wrong_words.update(tokens)
                        total_wrong += len(tokens)

                # Build vocabulary
                vocab = set(correct_words.keys()) | set(wrong_words.keys())
                vocab_size = len(vocab)

                if vocab_size == 0 or total_correct == 0 or total_wrong == 0:
                    continue

                # Laplace-smoothed log probabilities
                log_p_word_correct = {}
                log_p_word_wrong = {}
                for word in vocab:
                    log_p_word_correct[word] = math.log((correct_words[word] + 1) / (total_correct + vocab_size))
                    log_p_word_wrong[word] = math.log((wrong_words[word] + 1) / (total_wrong + vocab_size))

                prior_correct = correct_mask.sum() / len(edf)
                prior_wrong = wrong_mask.sum() / len(edf)

                eval_nb[eval_name] = {
                    'log_p_correct': log_p_word_correct,
                    'log_p_wrong': log_p_word_wrong,
                    'log_prior_correct': math.log(prior_correct + 1e-10),
                    'log_prior_wrong': math.log(prior_wrong + 1e-10),
                    'default_correct': math.log(1 / (total_correct + vocab_size)),
                    'default_wrong': math.log(1 / (total_wrong + vocab_size)),
                    'vocab_size': vocab_size,
                }

            self._nb_models[tier] = eval_nb

    def _predict_prob_correct(self, tier, eval_name, query):
        """Predict P(model correct | query) using Naive Bayes."""
        if tier not in self._nb_models:
            return self._eval_tier_acc.get(eval_name, {}).get(tier, 0.5)

        nb = self._nb_models[tier].get(eval_name)
        if nb is None:
            return self._eval_tier_acc.get(eval_name, {}).get(tier, 0.5)

        tokens = self._tokenize(str(query))
        if not tokens:
            return self._eval_tier_acc.get(eval_name, {}).get(tier, 0.5)

        log_correct = nb['log_prior_correct']
        log_wrong = nb['log_prior_wrong']

        for token in tokens:
            log_correct += nb['log_p_correct'].get(token, nb['default_correct'])
            log_wrong += nb['log_p_wrong'].get(token, nb['default_wrong'])

        # Convert to probability
        max_log = max(log_correct, log_wrong)
        p_correct = math.exp(log_correct - max_log)
        p_wrong = math.exp(log_wrong - max_log)
        total = p_correct + p_wrong

        return p_correct / total if total > 0 else 0.5

    def solve(self, query: str, eval_name: str, candidate_models: list) -> str:
        self._load()

        # Use NB to predict P(correct) for each tier, then pick best expected score
        best_tier = None
        best_expected = float('-inf')

        for tier in candidate_models:
            p_correct = self._predict_prob_correct(tier, eval_name, query)
            cost = self._tier_avg_cost.get(tier, 0)
            expected = p_correct - 150.0 * cost
            if expected > best_expected:
                best_expected = expected
                best_tier = tier

        if best_tier:
            return best_tier

        best = self._eval_best.get(eval_name, "mid")
        return best if best in candidate_models else "mid"
