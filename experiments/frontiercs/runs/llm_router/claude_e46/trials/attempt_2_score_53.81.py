import pandas as pd
import os
import sys

class Solution:
    def __init__(self):
        self._loaded = False
        self._eval_tier_stats = {}
        self._debug_done = False

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

        self._df = df
        all_cols = df.columns.tolist()

        # Parse model columns and cost columns
        model_cols = []
        cost_cols = {}
        response_cols = {}
        for c in all_cols:
            if '|total_cost' in c:
                model_name = c.replace('|total_cost', '')
                cost_cols[model_name] = c
            elif '|model_response' in c:
                model_name = c.replace('|model_response', '')
                response_cols[model_name] = c
            elif c not in ['sample_id', 'prompt', 'eval_name', 'oracle_model_to_route_to'] and '|' not in c:
                model_cols.append(c)

        self._model_cols = model_cols
        self._cost_cols = cost_cols

        # Print debug info
        avg_costs = {}
        avg_accs = {}
        for m in model_cols:
            if m in cost_cols:
                avg_costs[m] = df[cost_cols[m]].mean()
                avg_accs[m] = df[m].mean()

        self._avg_costs = avg_costs

        # Print to stderr for debugging
        print("=== MODEL STATS ===", file=sys.stderr)
        for m in sorted(avg_costs.keys(), key=lambda x: avg_costs[x]):
            print(f"  {m}: avg_cost={avg_costs[m]:.6f}, avg_acc={avg_accs.get(m,0):.4f}, score={avg_accs.get(m,0) - 150*avg_costs[m]:.4f}", file=sys.stderr)

        print(f"\n=== EVAL NAMES ({df['eval_name'].nunique()}) ===", file=sys.stderr)
        for en in df['eval_name'].unique():
            print(f"  {en}: {len(df[df['eval_name']==en])} samples", file=sys.stderr)

        print(f"\n=== ORACLE DIST ===", file=sys.stderr)
        if 'oracle_model_to_route_to' in df.columns:
            print(df['oracle_model_to_route_to'].value_counts().to_string(), file=sys.stderr)

        # Compute per-eval per-model scores
        # Map: cheap=mistral-7b, mid=mixtral-8x7b, expensive=gpt-4
        self._tier_map = {
            "cheap": "mistralai/mistral-7b-chat",
            "mid": "mistralai/mixtral-8x7b-chat",
            "expensive": "gpt-4-1106-preview",
        }

        # Per eval, per tier scores
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

        # Print tier stats per eval
        print(f"\n=== TIER SCORES PER EVAL ===", file=sys.stderr)
        for en, stats in self._eval_tier_stats.items():
            print(f"  {en}:", file=sys.stderr)
            for t, s in sorted(stats.items()):
                print(f"    {t}: acc={s['acc']:.4f}, cost={s['cost']:.6f}, score={s['score']:.4f}", file=sys.stderr)

    def solve(self, query: str, eval_name: str, candidate_models: list) -> str:
        self._load()

        stats = self._eval_tier_stats.get(eval_name, {})
        if not stats:
            return "cheap" if "cheap" in candidate_models else candidate_models[0]

        best_tier = max(candidate_models, key=lambda t: stats.get(t, {}).get('score', float('-inf')))
        return best_tier
