"""Reproducible random task selection for the Frontier-CS controlled comparison.

Draws N algorithmic problems with a fixed seed from the pool of valid, default-type (non-interactive)
problems that have testdata, excluding an explicit done-set. This is the exact procedure used to pick
the "random" tasks (non-cherry-picked, pre-committed seed).

Reproduce our draws (run from ~/frontier/Frontier-CS):
  python3 select_tasks.py --seed 42 --n 3 --exclude 0 1 5 15          -> ['211', '44', '9']
  python3 select_tasks.py --seed 43 --n 1 --exclude 0 1 5 9 15 44 47 147 185 192 211  -> ['22']
"""
import argparse, os, glob, random
try:
    import yaml
except ImportError:
    yaml = None

ROOT = "algorithmic/problems"


def valid_problems():
    out = []
    for i in os.listdir(ROOT):
        if not i.isdigit():
            continue
        p = os.path.join(ROOT, i)
        if not glob.glob(os.path.join(p, "testdata", "*.in")) or not os.path.exists(os.path.join(p, "config.yaml")):
            continue
        typ = "default"
        if yaml:
            try:
                typ = str((yaml.safe_load(open(os.path.join(p, "config.yaml"))) or {}).get("type", "default"))
            except Exception:
                pass
        if typ != "interactive":
            out.append(i)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--exclude", nargs="*", default=[])
    args = ap.parse_args()
    pool = sorted(set(valid_problems()) - set(args.exclude), key=int)
    random.seed(args.seed)
    pick = random.sample(pool, args.n) if args.n > 1 else [random.choice(pool)]
    print(f"pool_size={len(pool)} seed={args.seed}")
    print("PICK:", pick)


if __name__ == "__main__":
    main()
