import pandas as pd
import numpy as np
import os
import json

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

        # Save detailed stats
        stats = {
            'n_rows': len(df),
            'eval_names': df['eval_name'].unique().tolist(),
            'model_cols': model_cols,
            'cost_cols': list(cost_cols.keys()),
        }

        eval_stats = {}
        for eval_name in df['eval_name'].unique():
            edf = df[df['eval_name'] == eval_name]
            es = {'n': len(edf), 'tiers': {}}
            for tier, model in self._tier_map.items():
                if model in model_cols and model in cost_cols:
                    acc = float(edf[model].mean())
                    cost = float(edf[cost_cols[model]].mean())
                    score = acc - 150.0 * cost
                    es['tiers'][tier] = {'acc': round(acc, 4), 'cost': round(cost, 8), 'score': round(score, 4)}
            eval_stats[eval_name] = es

        stats['eval_stats'] = eval_stats

        # Oracle tier distribution
        tier_order = ["cheap", "mid", "expensive"]
        oracle_dist = {}
        for eval_name in df['eval_name'].unique():
            edf = df[df['eval_name'] == eval_name]
            dist = {}
            for _, row in edf.iterrows():
                opt = "cheap"
                for t in tier_order:
                    m = self._tier_map[t]
                    if m in model_cols and row.get(m, 0) == 1.0:
                        opt = t
                        break
                dist[opt] = dist.get(opt, 0) + 1
            total = sum(dist.values())
            oracle_dist[eval_name] = {k: round(v/total, 4) for k, v in dist.items()}
        stats['oracle_dist'] = oracle_dist

        # Write stats to a file
        try:
            out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data_stats.json')
            with open(out_path, 'w') as f:
                json.dump(stats, f, indent=2)
        except:
            pass

        # Per-eval best tier
        self._eval_best = {}
        for eval_name, es in eval_stats.items():
            best_tier = "mid"
            best_score = float('-inf')
            for tier, ts in es['tiers'].items():
                if ts['score'] > best_score:
                    best_score = ts['score']
                    best_tier = tier
            self._eval_best[eval_name] = best_tier

    def solve(self, query: str, eval_name: str, candidate_models: list) -> str:
        self._load()
        best = self._eval_best.get(eval_name, "mid")
        return best if best in candidate_models else "mid"
