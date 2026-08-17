"""Stochastic workloads: seeded, recorded, and paired at the terminal stage.

Spec §3.7 oracle 3 and §3.8. A systems target (a queue, a cache, an
autoscaler) is stochastic, and its run-to-run variance is usually larger than
the effect the campaign is trying to measure. Two things follow, and this file
is the oracle for both:

1. **Every measurement row carries a seed.** Not so the numbers stop moving —
   they should move, that is the workload — but so the movement is a recorded
   input rather than an unlogged one. A row whose seed is on disk can be
   re-measured; a row whose seed came from ``/dev/urandom`` inside the target
   cannot, and neither can the campaign's own reviewer.

2. **The terminal comparison is PAIRED.** Common random numbers: within one
   ``confirm`` round, replicate *i* of every finalist runs the SAME seed, so
   the seed's contribution cancels out of the finalist-to-finalist difference.
   ``certificate.terminal_regret_bound`` then reads the differences directly
   (``bonferroni_one_sided_t_paired``) instead of Welch-combining two
   independent variances, and the bound shrinks by whatever fraction of the
   variance the workload contributed. On a noisy server that fraction is most
   of it, which is the difference between a campaign that can certify inside
   its budget and one that cannot.

Not asserted here: that the seed changes the number. That is
``synthetic.make_synthetic_runner``'s business and is covered by
``test_a_row_seed_actually_drives_the_synthetic_noise`` below; the campaign-level
claims above hold regardless of how the target consumes ``NOUS_WORKLOAD_SEED``.
"""
from __future__ import annotations

import json

import pytest

from orchestrator.optimize.harness import run_synthetic_campaign
from orchestrator.optimize.synthetic import SURFACES


def _run(tmp_path, seed):
    return run_synthetic_campaign(
        SURFACES["additive"](), seed=seed, parent_dir=tmp_path,
        campaign_overrides={"workload": {"seed_env": "NOUS_WORKLOAD_SEED"},
                            "design": {"screen": {"resolution": 5, "center_points": 4},
                                       "refine": {"kind": "central_composite", "center_points": 4},
                                       "confirm": {"replicates": 4, "shortlist_size": 3}}},
    )


def test_every_row_records_its_workload_seed(tmp_path):
    res = _run(tmp_path, 41)
    dm = json.loads((res.work_dir / "runs" / "iter-2" / "design_matrix.json").read_text())
    assert len(dm["workload_seeds"]) == len(dm["rows"])
    assert all("NOUS_WORKLOAD_SEED" in r["apply"]["env"] for r in dm["rows"])


def test_confirm_uses_common_random_numbers_and_a_paired_bound(tmp_path):
    res = _run(tmp_path, 42)
    conf_iters = [json.loads(l)["iteration"] for l in (res.work_dir / "transitions.jsonl").read_text().splitlines()
                  if json.loads(l)["from"] == "confirm"]
    dm = json.loads((res.work_dir / "runs" / f"iter-{conf_iters[0]}" / "design_matrix.json").read_text())
    by_rep = {}
    for r in dm["rows"]:
        by_rep.setdefault(r["replicate"], set()).add(r["apply"]["env"]["NOUS_WORKLOAD_SEED"])
    assert all(len(seeds) == 1 for seeds in by_rep.values())        # CRN within a replicate block
    conf = json.loads((res.work_dir / "runs" / f"iter-{conf_iters[0]}" / "confirmation.json").read_text())
    assert conf["paired"] is True


def test_seed_env_name_is_validated():
    from orchestrator.optimize.harness import synthetic_campaign
    from orchestrator.validate import validate_optimization_campaign
    c = synthetic_campaign(SURFACES["additive"](), workload={"seed_env": "bad name"})
    assert any("seed_env" in e for e in validate_optimization_campaign(c))


def _workload_errors(workload):
    from orchestrator.optimize.harness import synthetic_campaign
    from orchestrator.validate import validate_optimization_campaign
    c = synthetic_campaign(SURFACES["additive"](), workload=workload)
    return [e for e in validate_optimization_campaign(c)
            if "workload" in e and not e.startswith("WARN:")]


@pytest.mark.parametrize("name", [
    "bad name", "lower_case", "9LEADING", "HAS-HYPHEN", "with.dot", "", "SPACE ",
])
def test_illegal_seed_env_names_are_rejected(name):
    """Every shape `os.environ` accepts and a target's shell cannot read.

    Python does not police environment keys, so all of these are exported
    successfully and then unreadable — `$bad name` is two words to every POSIX
    shell. Nothing raises; the seed is simply never read, every replicate draws a
    fresh workload, and `confirm` still reports a PAIRED bound over differences
    whose shared term never cancelled. That bound remains valid — its variance
    comes from the observed differences, not from an assumed cancellation — but
    it is less efficient than the unpaired form and the certificate on disk
    claims `bonferroni_one_sided_t_paired` for an experiment that paired
    nothing. Nothing else on disk records that, which is why the check has to be
    here.
    """
    hits = _workload_errors({"seed_env": name})
    assert hits, f"{name!r} was accepted"
    assert any("seed_env" in h for h in hits), hits


@pytest.mark.parametrize("name", ["NOUS_WORKLOAD_SEED", "SEED", "_S", "A9_B"])
def test_legal_seed_env_names_are_accepted(name):
    """The half that makes the regex an oracle rather than a blanket refusal."""
    assert _workload_errors({"seed_env": name}) == [], name


@pytest.mark.parametrize("seeds", [[], [1.5], [True], "notalist"])
def test_malformed_declared_seeds_are_rejected(seeds):
    """`seeds` is taken modulo an index and exported as a string.

    An empty list has no element to take, so the campaign would silently fall
    back to derived seeds while the file reads as if it had pinned them — the
    reproducibility claim the field exists to make, quietly withdrawn. A float or
    a bool arrives in the target's environment as '1.5' or 'True', and whatever
    the target does with that is not a seed.
    """
    hits = _workload_errors({"seed_env": "WL", "seeds": seeds})
    assert hits, f"{seeds!r} was accepted"
    assert any("seeds" in h for h in hits), hits


def test_a_well_formed_workload_block_passes_clean():
    assert _workload_errors({"seed_env": "WL", "seeds": [1, 2, 3]}) == []


# ── discrimination: the two tests above must FAIL on a broken assignment ─────
#
# The brief's two tests are the task's oracle, and an oracle that passes on a
# plausible mistake is not one. Both mistakes below were reachable from the
# brief's own pseudocode — a `_seed` keyed on the wrong index, and a `paired`
# flag written to a payload nothing reads — so the properties they violate are
# asserted directly rather than being left implicit in an aggregate count.


def test_distinct_replicate_blocks_get_distinct_seeds(tmp_path):
    """CRN is "same seed ACROSS finalists", not "one seed for the campaign".

    A `_seed` that ignored its index entirely would satisfy the CRN test above
    (one seed per replicate block, trivially) while destroying the point of
    replication: four replicates of one seed measure the same workload draw
    four times, so the paired variance estimate is an estimate of the
    measurement noise alone and the bound it produces is a fiction. So the
    blocks must DIFFER as strictly as they must internally agree.
    """
    res = _run(tmp_path, 42)
    conf_iters = [json.loads(l)["iteration"]
                  for l in (res.work_dir / "transitions.jsonl").read_text().splitlines()
                  if json.loads(l)["from"] == "confirm"]
    dm = json.loads(
        (res.work_dir / "runs" / f"iter-{conf_iters[0]}" / "design_matrix.json").read_text())
    per_block = {}
    for r in dm["rows"]:
        per_block.setdefault(r["replicate"], set()).add(
            r["apply"]["env"]["NOUS_WORKLOAD_SEED"])
    assert len(per_block) > 1, "need >1 replicate to make the claim at all"
    seeds = [next(iter(v)) for v in per_block.values()]
    assert len(set(seeds)) == len(seeds), f"replicate blocks share a seed: {per_block}"


def test_each_finalists_seed_sequence_is_positionally_identical(tmp_path):
    """The invariant `terminal_regret_bound`'s paired `zip` silently depends on.

    That function pairs `samples[best][i]` with `samples[k][i]` POSITIONALLY. It
    has no access to replicate indices — `_finish_confirm` appends each
    finalist's measurements in row order and hands over bare lists. So "every
    finalist's replicate i shares a seed" is not sufficient on its own: the
    sequences must also be in the SAME ORDER, or position i of one finalist would
    be paired against a different replicate of another and the shared term would
    not cancel. It holds because `_confirm_rows` emits one complete replicate
    block at a time (the run-order shuffle is INSIDE a block, never across) and
    `run_stage` restores design order before `_finish_confirm` reads anything
    positionally — but that is three separate facts in three functions, so it is
    pinned here rather than left to hold by coincidence.
    """
    res = _run(tmp_path, 42)
    conf_iters = [json.loads(l)["iteration"]
                  for l in (res.work_dir / "transitions.jsonl").read_text().splitlines()
                  if json.loads(l)["from"] == "confirm"]
    dm = json.loads(
        (res.work_dir / "runs" / f"iter-{conf_iters[0]}" / "design_matrix.json").read_text())
    assert dm["run_order"] == list(range(len(dm["rows"]))), (
        "confirm's payload run_order must stay the identity, or design order is "
        "not the order `_finish_confirm` sees"
    )
    seq: dict[int, list[int]] = {}
    for r in dm["rows"]:
        seq.setdefault(r["apply"]["finalist"], []).append(
            r["apply"]["env"]["NOUS_WORKLOAD_SEED"])
    assert len(seq) > 1, "need >1 finalist for a pairing claim"
    assert len(set(map(tuple, seq.values()))) == 1, (
        f"finalists' seed sequences differ in order: {seq}"
    )


def test_screen_rows_get_per_row_seeds_not_one_shared_seed(tmp_path):
    """The spending stages vary the seed PER ROW, unlike confirm.

    Outside the terminal comparison there is no pairing to preserve: a screen
    is a fit over distinct configurations, and giving all of them one seed
    would confound the whole block with a single workload draw. `row_index`
    (not `replicate`, which is None outside confirm) is the key there.
    """
    res = _run(tmp_path, 41)
    dm = json.loads(
        (res.work_dir / "runs" / "iter-2" / "design_matrix.json").read_text())
    seeds = [r["apply"]["env"]["NOUS_WORKLOAD_SEED"] for r in dm["rows"]]
    assert len(set(seeds)) == len(seeds), f"screen rows share seeds: {seeds}"


def test_the_recorded_seed_is_the_seed_the_rows_carry(tmp_path):
    """design_matrix.json's three records of the same fact must agree.

    The helper produces THREE structures from one decision: the returned
    ConfigRow list (what actually executes), `payload["rows"]` (the
    pre-registered per-row record), and `payload["workload_seeds"]` (the
    index -> seed summary). They are separate objects and can therefore
    disagree — and a payload recording seeds the rows never carried is the worst
    outcome available, a pre-registration asserting a reproducibility guarantee
    the run did not provide.

    The two payload halves are compared here against the artifact; the
    ConfigRow half is compared against them in
    `test_the_helper_seeds_the_rows_and_the_payload_identically`, which can hold
    the objects rather than only their serialisation (`runs.jsonl` records
    `levels`/`role`/`replicate`, not `apply`, so the executed env is not on disk
    to compare against).
    """
    res = _run(tmp_path, 41)
    it = res.work_dir / "runs" / "iter-2"
    dm = json.loads((it / "design_matrix.json").read_text())
    declared = {int(k): v for k, v in dm["workload_seeds"].items()}
    in_payload = {r["row_index"]: r["apply"]["env"]["NOUS_WORKLOAD_SEED"]
                  for r in dm["rows"]}
    assert declared == in_payload


def test_the_helper_seeds_the_rows_and_the_payload_identically():
    """The executing rows and the pre-registered payload cannot diverge.

    Called at the seam rather than through a campaign, because this is the one
    property no artifact can witness: `runs.jsonl` does not record `apply`, so
    if the ConfigRow list carried different seeds from the payload that recorded
    them, every campaign-level assertion in this file would still pass while the
    run measured something the pre-registration does not describe.
    """
    from orchestrator.optimize.matrix import ConfigRow
    from orchestrator.optimize.stage_runner import _assign_workload_seeds

    rows = [
        ConfigRow(row_index=i, levels={"A": i}, role="confirm", replicate=i % 2,
                  apply={"args": [f"--a={i}"]})
        for i in range(4)
    ]
    payload = {
        "run_order_seed": 3,
        "rows": [{"row_index": r.row_index, "levels": dict(r.levels),
                  "role": r.role, "replicate": r.replicate, "apply": dict(r.apply)}
                 for r in rows],
    }
    pol = {"workload": {"seed_env": "WL"}}
    out, new_payload = _assign_workload_seeds(
        rows, payload, pol, iteration=5, confirm=True,
    )
    from_rows = {r.row_index: r.apply["env"]["WL"] for r in out}
    from_payload = {r["row_index"]: r["apply"]["env"]["WL"]
                    for r in new_payload["rows"]}
    assert from_rows == from_payload
    assert from_rows == {int(k): v for k, v in new_payload["workload_seeds"].items()}
    # Pre-existing `apply` content survives — the env is merged, not substituted.
    assert all(r.apply["args"] == [f"--a={r.row_index}"] for r in out)
    # Replicate index, not row index, keys the confirm seeds: rows 0/2 pair and
    # rows 1/3 pair, which IS the common-random-numbers property.
    assert from_rows[0] == from_rows[2] and from_rows[1] == from_rows[3]
    assert from_rows[0] != from_rows[1]
    # The original inputs are untouched (the caller still holds them).
    assert "env" not in rows[0].apply
    assert "workload_seeds" not in payload


def test_the_paired_flag_reaches_the_bound_not_just_the_artifact(tmp_path):
    """`paired: True` must change the ESTIMATOR, not only a JSON field.

    `payload["paired"]` is consumed by `_finish_confirm`, which forwards it to
    `certificate.terminal_regret_bound`, which switches from Welch's
    unequal-variance t to the paired-difference t and names the choice in
    `RegretBound.method`. Writing the flag and leaving the bound unpaired would
    satisfy `conf["paired"] is True` while the campaign kept reporting the
    wider bound — the whole task, silently a no-op. The recorded `method` is
    the only place that distinction is visible on disk.

    Guarded on the branch, not asserted unconditionally: the paired path needs
    >= 2 finalists that each survived with matched replicate counts, and a
    round where measured invalidity excluded one is a legitimate outcome of the
    surface, not a defect in the wiring.
    """
    res = _run(tmp_path, 42)
    conf_iters = [json.loads(l)["iteration"]
                  for l in (res.work_dir / "transitions.jsonl").read_text().splitlines()
                  if json.loads(l)["from"] == "confirm"]
    conf = json.loads(
        (res.work_dir / "runs" / f"iter-{conf_iters[0]}" / "confirmation.json").read_text())
    assert conf["paired"] is True
    method = (conf.get("terminal_bound") or {}).get("method")
    if method not in (None, "none", "trivial"):
        assert method == "bonferroni_one_sided_t_paired", (
            f"paired was recorded but the bound used {method!r}"
        )


def test_pairing_is_what_makes_a_noisy_target_certifiable():
    """The claim spec §3.8 makes, measured rather than asserted.

    Everything above checks that the pairing is WIRED. This checks that it is
    WORTH wiring, because if it were not, the whole task would be machinery in
    service of nothing and no other test would notice.

    The construction is the systems case the kind exists for: two finalists whose
    true means differ by 0.10, a workload term of sd 1.0 that CRN makes common to
    replicate *i* of both, and independent measurement noise of sd 0.05. The
    workload term dominates the effect by 10x — a queue, a cache, an autoscaler.
    Handed the SAME measurements, the two estimators disagree about whether the
    campaign may certify at all.
    """
    import random

    from orchestrator.optimize import certificate

    rng = random.Random(0)
    n = 6
    shared = [rng.gauss(0, 1.0) for _ in range(n)]        # the common workload draw
    samples = {
        "f0": [10.00 + s + rng.gauss(0, 0.05) for s in shared],
        "f1": [10.10 + s + rng.gauss(0, 0.05) for s in shared],
    }
    kw = dict(delta=0.05, direction="maximize")
    paired = certificate.terminal_regret_bound(samples, "f1", paired=True, **kw)
    unpaired = certificate.terminal_regret_bound(samples, "f1", paired=False, **kw)

    assert paired.method == "bonferroni_one_sided_t_paired"
    assert unpaired.method == "bonferroni_one_sided_welch_t"
    assert paired.value < unpaired.value, (
        f"pairing did not tighten the bound: {paired.value} vs {unpaired.value}"
    )
    # And the difference straddles a decision, not just a decimal: with an
    # indifference width of 0.05 the paired bound certifies and the unpaired one
    # cannot, on identical numbers.
    epsilon = 0.05
    assert paired.value <= epsilon < unpaired.value


def test_declared_seeds_are_used_verbatim_and_cycled(tmp_path):
    """`workload.seeds: [...]` is the author's own seed set, not a hint.

    A campaign that pins its seeds is reproducing a specific set of workload
    draws (the same traces a paper reported, say). The compiled policy carries
    them, and the assignment must take them modulo the index rather than
    hashing them into something else.
    """
    res = run_synthetic_campaign(
        SURFACES["additive"](), seed=7, parent_dir=tmp_path,
        campaign_overrides={
            "workload": {"seed_env": "WL", "seeds": [11, 22]},
            "stages": ["verify", "screen", "confirm"],
            "design": {"screen": {"resolution": 5, "center_points": 4},
                       "confirm": {"replicates": 4, "shortlist_size": 2}},
        },
    )
    dm = json.loads(
        (res.work_dir / "runs" / "iter-2" / "design_matrix.json").read_text())
    for r in dm["rows"]:
        assert r["apply"]["env"]["WL"] == [11, 22][r["row_index"] % 2]

    conf_iters = [json.loads(l)["iteration"]
                  for l in (res.work_dir / "transitions.jsonl").read_text().splitlines()
                  if json.loads(l)["from"] == "confirm"]
    cdm = json.loads(
        (res.work_dir / "runs" / f"iter-{conf_iters[0]}" / "design_matrix.json").read_text())
    for r in cdm["rows"]:
        assert r["apply"]["env"]["WL"] == [11, 22][r["replicate"] % 2]


def test_no_workload_block_changes_nothing(tmp_path):
    """The field is opt-in: an existing campaign's artifacts do not move.

    A campaign with no `workload` gets no `env` key it did not have, no
    `workload_seeds`, and — critically — NO `paired: True`. Not because the
    paired bound would be unsound: it estimates its variance from the observed
    differences, so an absent cancellation never narrows them and coverage stays
    nominal. Rather because it would buy nothing (fewer degrees of freedom spent
    on a common term that was not common) while the certificate on disk would
    record `bonferroni_one_sided_t_paired` for an experiment that paired
    nothing — a provenance defect, not an unsound number.
    """
    res = run_synthetic_campaign(
        SURFACES["additive"](), seed=5, parent_dir=tmp_path,
        campaign_overrides={"stages": ["verify", "screen", "confirm"],
                            "design": {"screen": {"resolution": 5, "center_points": 4},
                                       "confirm": {"replicates": 3, "shortlist_size": 2}}},
    )
    dm = json.loads(
        (res.work_dir / "runs" / "iter-2" / "design_matrix.json").read_text())
    assert "workload_seeds" not in dm
    conf_iters = [json.loads(l)["iteration"]
                  for l in (res.work_dir / "transitions.jsonl").read_text().splitlines()
                  if json.loads(l)["from"] == "confirm"]
    conf = json.loads(
        (res.work_dir / "runs" / f"iter-{conf_iters[0]}" / "confirmation.json").read_text())
    assert conf["paired"] is False


def test_a_row_seed_actually_drives_the_synthetic_noise():
    """The oracle's own target must honour the seed, or oracle 3 is untested.

    `make_synthetic_runner(..., seed_env=...)` draws its noise from
    `Random(row_seed)` rather than from the shared stream, which is what makes
    the harness a model of a seeded systems target: two rows at the SAME levels
    with the SAME seed must return the same number, and with different seeds
    must not. Without this, every CRN assertion above would hold over a runner
    for which the seed was decoration.
    """
    from orchestrator.optimize.matrix import ConfigRow
    from orchestrator.optimize.synthetic import make_synthetic_runner

    surface = SURFACES["additive"]()
    levels = {"A": 8, "B": 8, "C": "on"}

    def row(i, seed):
        return ConfigRow(row_index=i, levels=dict(levels), role="confirm",
                         replicate=0, apply={"env": {"WL": seed}})

    run = make_synthetic_runner(surface, seed=1, seed_env="WL")
    same_a = run(row(0, 99))["m"]
    same_b = run(row(1, 99))["m"]
    other = run(row(2, 100))["m"]
    assert same_a == same_b, "same seed, same levels -> the noise must repeat"
    assert same_a != other, "a different seed must give a different draw"

    # And the shared-stream behaviour is untouched when no seed_env is declared.
    plain = make_synthetic_runner(surface, seed=1)
    assert plain(row(0, 99))["m"] != plain(row(1, 99))["m"]
