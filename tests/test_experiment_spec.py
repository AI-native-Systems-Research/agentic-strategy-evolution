"""Tests for the operational ``experiment_spec`` block on bundles
(#209/#210) and the ``bundle_amendments.jsonl`` drift record (#211).

The block lets DESIGN pin operational decisions (build commands, fan-out
template, classification logic, verified parameters) so EXECUTE_ANALYZE
doesn't re-derive them in a fresh worktree. Amendments record overrides
EXECUTE_ANALYZE makes during smoke / validation, so REPORT can surface
the drift instead of describing the prescribed bundle.

No live LLM calls — pure schema validation + helpers + LLMDispatcher
seam injection.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import jsonschema
import pytest
import yaml

from orchestrator.llm_dispatch import (
    LLMDispatcher,
    _format_bundle_amendments_summary,
)


SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "orchestrator" / "schemas"


def _load_bundle_schema() -> dict:
    return yaml.safe_load((SCHEMAS_DIR / "bundle.schema.yaml").read_text())


def _make_bundle(*, experiment_spec: dict | None = None) -> dict:
    bundle: dict = {
        "metadata": {
            "iteration": 1, "family": "test",
            "research_question": "Does X work?",
        },
        "arms": [
            {"type": "h-main", "prediction": "p", "mechanism": "m",
             "diagnostic": "d"},
        ],
    }
    if experiment_spec is not None:
        bundle["experiment_spec"] = experiment_spec
    return bundle


def _make_completion(responses: list[str]):
    call_log: list[dict] = []
    idx = {"n": 0}

    def _fn(**kwargs):
        call_log.append(kwargs)
        resp = MagicMock()
        resp.choices = [
            MagicMock(message=MagicMock(content=responses[idx["n"]])),
        ]
        idx["n"] += 1
        return resp

    _fn.call_log = call_log  # type: ignore[attr-defined]
    return _fn


def _make_campaign() -> dict:
    return {
        "research_question": "?",
        "target_system": {
            "name": "TestSys", "description": "test",
            "observable_metrics": ["m"], "controllable_knobs": ["k"],
        },
        "prompts": {"methodology_layer": "prompts/methodology",
                    "domain_adapter_layer": None},
    }


# ─── Schema acceptance for experiment_spec ───────────────────────────────


class TestSchemaAcceptsExperimentSpec:
    def test_no_experiment_spec_validates(self):
        """Backward compat: bundles without experiment_spec still pass."""
        jsonschema.validate(_make_bundle(), _load_bundle_schema())

    def test_preflight_commands_validates(self):
        b = _make_bundle(experiment_spec={
            "preflight_commands": ["go build -o blis main.go"],
        })
        jsonschema.validate(b, _load_bundle_schema())

    def test_full_experiment_spec_validates(self):
        b = _make_bundle(experiment_spec={
            "preflight_commands": ["go build -o blis main.go"],
            "fanout_template":
                "cat /tmp/args.txt | parallel -j $N './blis run {} > {}.log 2>&1'",
            "classification_function":
                "lambda r: 'adv' if r['num_prefill_tokens'] > 4096 else 'coop'",
            "verified_parameters": {"total_kv_blocks": 1200, "horizon_us": 3e8},
        })
        jsonschema.validate(b, _load_bundle_schema())

    def test_preflight_must_be_list_of_strings(self):
        b = _make_bundle(experiment_spec={"preflight_commands": "go build"})
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(b, _load_bundle_schema())

    def test_empty_string_in_preflight_rejected(self):
        b = _make_bundle(experiment_spec={"preflight_commands": [""]})
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(b, _load_bundle_schema())

    def test_typo_field_rejected(self):
        """#2 critical-fix regression: experiment_spec is additionalProperties:
        false, so a typo'd field name (preflight_command singular,
        verifid_parameters, etc.) fails validation loudly instead of
        silently skipping the operational handoff."""
        b = _make_bundle(experiment_spec={
            "preflight_command": ["build"],  # typo: should be plural
        })
        with pytest.raises(jsonschema.ValidationError, match="preflight_command"):
            jsonschema.validate(b, _load_bundle_schema())

    def test_unknown_top_level_field_rejected(self):
        b = _make_bundle(experiment_spec={
            "preflight_commands": ["build"],
            "verifid_parameters": {"x": 1},  # typo
        })
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(b, _load_bundle_schema())

    def test_verified_parameters_keeps_open_value_namespace(self):
        """#2 fix scope: verified_parameters is the one place where
        additionalProperties: true is correct — it's a target-knob
        namespace and the keys can't be enumerated. Verify the locked
        outer block doesn't accidentally lock down inner knobs."""
        b = _make_bundle(experiment_spec={
            "verified_parameters": {
                "any_target_knob": 1100,
                "another_one": "string-value",
                "nested": {"k": 2},
            },
        })
        jsonschema.validate(b, _load_bundle_schema())


# ─── #211: bundle_amendments.jsonl rendering ─────────────────────────────


class TestBundleAmendmentsSummary:
    def test_no_runs_dir_returns_friendly_marker(self, tmp_path: Path) -> None:
        out = _format_bundle_amendments_summary(tmp_path / "campaign")
        assert "no iteration directories" in out.lower()

    def test_no_amendments_files_returns_clean_marker(
            self, tmp_path: Path) -> None:
        wd = tmp_path / "campaign"
        (wd / "runs" / "iter-1").mkdir(parents=True)
        out = _format_bundle_amendments_summary(wd)
        assert "no bundle_amendments" in out.lower()

    def test_renders_single_amendment(self, tmp_path: Path) -> None:
        wd = tmp_path / "campaign"
        inputs = wd / "runs" / "iter-1" / "inputs"
        inputs.mkdir(parents=True)
        (inputs / "bundle_amendments.jsonl").write_text(json.dumps({
            "parameter": "total_kv_blocks",
            "prescribed_value": 1100,
            "actual_value": 1200,
            "reason": "smoke produced dropped_unservable=120",
        }) + "\n")

        out = _format_bundle_amendments_summary(wd)
        assert "iter-1" in out
        assert "total_kv_blocks" in out
        assert "1100" in out
        assert "1200" in out
        assert "dropped_unservable" in out

    def test_renders_multiple_amendments(self, tmp_path: Path) -> None:
        wd = tmp_path / "campaign"
        inputs = wd / "runs" / "iter-1" / "inputs"
        inputs.mkdir(parents=True)
        rows = [
            json.dumps({"parameter": "kv_blocks", "prescribed_value": 1100,
                        "actual_value": 1200, "reason": "drop fix"}),
            json.dumps({"parameter": "horizon", "prescribed_value": 60,
                        "actual_value": 300, "reason": "burst tail"}),
        ]
        (inputs / "bundle_amendments.jsonl").write_text("\n".join(rows) + "\n")

        out = _format_bundle_amendments_summary(wd)
        assert "2 amendment(s)" in out
        assert "kv_blocks" in out
        assert "horizon" in out

    def test_malformed_lines_surfaced_not_silently_skipped(
            self, tmp_path: Path) -> None:
        """A corrupted amendment line is *exactly* the divergence #211
        was added to surface. Skipping it silently re-introduces the
        silence — the helper must announce the skip count so operators
        know the amendment record may be incomplete."""
        wd = tmp_path / "campaign"
        inputs = wd / "runs" / "iter-1" / "inputs"
        inputs.mkdir(parents=True)
        (inputs / "bundle_amendments.jsonl").write_text(
            json.dumps({"parameter": "kv_blocks", "prescribed_value": 1100,
                        "actual_value": 1200, "reason": "valid row"}) + "\n"
            + "not valid json {\n"
            + "{\"another_invalid\":\n"
            + json.dumps({"parameter": "p2", "prescribed_value": 1,
                          "actual_value": 2, "reason": "another valid row"}) + "\n"
        )

        out = _format_bundle_amendments_summary(wd)
        # The valid rows render
        assert "kv_blocks" in out
        assert "p2" in out
        # The malformed lines are SURFACED, not silently dropped
        assert "malformed" in out.lower()
        assert "2" in out  # 2 malformed lines

    def test_unreadable_amendments_log_surfaced(
            self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When read_text raises OSError (e.g., permission denied), the
        helper produces a visible row instead of silently dropping the
        iter from the report's view."""
        wd = tmp_path / "campaign"
        inputs = wd / "runs" / "iter-1" / "inputs"
        inputs.mkdir(parents=True)
        log = inputs / "bundle_amendments.jsonl"
        log.write_text("{}")  # exists; we'll patch read_text

        from pathlib import Path as _Path
        original_read_text = _Path.read_text

        def _failing_read_text(self, *args, **kwargs):
            if self == log:
                raise PermissionError("simulated unreadable")
            return original_read_text(self, *args, **kwargs)

        monkeypatch.setattr(_Path, "read_text", _failing_read_text)

        out = _format_bundle_amendments_summary(wd)
        assert "unreadable" in out.lower()
        assert "PermissionError" in out

    def test_caps_long_amendment_lists(self, tmp_path: Path) -> None:
        wd = tmp_path / "campaign"
        inputs = wd / "runs" / "iter-1" / "inputs"
        inputs.mkdir(parents=True)
        rows = [
            json.dumps({"parameter": f"p{i}", "prescribed_value": i,
                        "actual_value": i + 1, "reason": "x"})
            for i in range(50)
        ]
        (inputs / "bundle_amendments.jsonl").write_text("\n".join(rows) + "\n")

        out = _format_bundle_amendments_summary(wd)
        assert "50 amendment(s)" in out
        assert "and 30 more" in out  # 50 - 20 cap


class TestReportContextIncludesAmendments:
    """#211: REPORT extractor's prompt must include the amendment summary
    so the report can surface 'we ran with kv_blocks=1200, not the bundle's
    1100'."""

    def test_amendments_appear_in_extractor_prompt(
            self, tmp_path: Path,
            monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        # Set up an iter with both results and an amendment.
        results = tmp_path / "runs" / "iter-1" / "results"
        results.mkdir(parents=True)
        (results / "h-main_seed42.json").write_text("{}")

        inputs = tmp_path / "runs" / "iter-1" / "inputs"
        inputs.mkdir(parents=True)
        (inputs / "bundle_amendments.jsonl").write_text(json.dumps({
            "parameter": "total_kv_blocks",
            "prescribed_value": 1100,
            "actual_value": 1200,
            "reason": "smoke showed dropped_unservable",
        }) + "\n")

        (tmp_path / "ledger.json").write_text(json.dumps({"iterations": []}))
        (tmp_path / "principles.json").write_text(json.dumps({"principles": []}))

        d = LLMDispatcher(
            work_dir=tmp_path,
            campaign=_make_campaign(),
            completion_fn=_make_completion(["# stub report"]),
        )
        d.dispatch(
            "extractor", "report",
            output_path=tmp_path / "report.md",
            iteration=0,
        )

        all_prompt = ""
        for call in d._completion.call_log:  # type: ignore[attr-defined]
            for msg in call.get("messages", []):
                all_prompt += msg.get("content", "") + "\n"

        assert "total_kv_blocks" in all_prompt, (
            "#211: REPORT extractor must see bundle_amendments so the "
            "report can describe the actually-executed parameters."
        )
        assert "1200" in all_prompt
        assert "1100" in all_prompt


# ─── #222: rehearsal_subset structured field ─────────────────────────────


class TestRehearsalSubsetSchema:
    """#222: bundle.experiment_spec.rehearsal_subset declares iter-1's
    execution scope. The post-#212 paper-burst rerun showed that
    methodology prose alone doesn't scope-shrink reliably; this is the
    structured backup."""

    def test_rehearsal_subset_validates(self):
        b = _make_bundle(experiment_spec={
            "rehearsal_subset": {
                "seeds": [42],
                "arms": ["h-main", "h-control-negative"],
                "extra_validation_only": True,
            },
        })
        jsonschema.validate(b, _load_bundle_schema())

    def test_rehearsal_subset_minimal(self):
        """``seeds`` and ``arms`` are the only meaningful fields;
        extra_validation_only defaults to false (omitted)."""
        b = _make_bundle(experiment_spec={
            "rehearsal_subset": {
                "seeds": [42],
                "arms": ["h-main"],
            },
        })
        jsonschema.validate(b, _load_bundle_schema())

    def test_rehearsal_subset_unknown_field_rejected(self):
        b = _make_bundle(experiment_spec={
            "rehearsal_subset": {
                "seeds": [42],
                "arms": ["h-main"],
                "unknown_field": "x",
            },
        })
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(b, _load_bundle_schema())

    def test_rehearsal_subset_empty_arms_rejected(self):
        b = _make_bundle(experiment_spec={
            "rehearsal_subset": {
                "seeds": [42],
                "arms": [],   # minItems: 1
            },
        })
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(b, _load_bundle_schema())


# ─── #226: timing_observations + watchdog override ────────────────────────


class TestTimingObservationsSchema:
    """#226: timing_observations records per-policy wall-time observations
    from rehearsal feasibility probes. iter-2's SDKDispatcher reads
    `recommended_turn_silence_threshold_seconds` to calibrate the
    watchdog."""

    def test_timing_observations_validates(self):
        b = _make_bundle(experiment_spec={
            "timing_observations": {
                "expected_wall_time_seconds_per_policy": {
                    "ea-wfq": 25.0,
                    "wfq": 23.0,
                    "drf": 28.0,
                    "externality-credit": 95.0,
                    "none": 22.0,
                },
                "recommended_turn_silence_threshold_seconds": 360.0,
                "observation_method":
                    "feasibility probe at seed=42, single arm per policy",
            },
        })
        jsonschema.validate(b, _load_bundle_schema())

    def test_timing_observations_unknown_field_rejected(self):
        b = _make_bundle(experiment_spec={
            "timing_observations": {
                "expected_wall_time_seconds_per_policy": {"ea-wfq": 25},
                "recommended_turn_silence_threshold_seconds": 360,
                "another_typo_field": "x",
            },
        })
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(b, _load_bundle_schema())

    def test_negative_threshold_rejected(self):
        b = _make_bundle(experiment_spec={
            "timing_observations": {
                "recommended_turn_silence_threshold_seconds": -1,
            },
        })
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(b, _load_bundle_schema())


def _campaign_with_default_threshold(repo: Path | None = None) -> dict:
    """Campaign with the default sdk_timeouts (silence + turn = 600s)."""
    target = {
        "name": "TestSys", "description": "test",
        "observable_metrics": ["m"], "controllable_knobs": ["k"],
    }
    if repo is not None:
        target["repo_path"] = str(repo)
    return {
        "research_question": "?",
        "target_system": target,
        "prompts": {"methodology_layer": "prompts/methodology",
                    "domain_adapter_layer": None},
    }


class TestWatchdogReadsBundleOverride:
    """#226: ``SDKDispatcher.dispatch`` should resolve the watchdog
    threshold per-iter from the prior iter's bundle.experiment_spec.
    timing_observations.recommended_turn_silence_threshold_seconds —
    falling back to the campaign-level default (or factory default)
    when the bundle doesn't carry one. Tests the resolver as a pure
    function (no SDK needed) AND the dispatcher's per-call override.
    """

    def test_resolver_reads_recommended_threshold(self, tmp_path: Path) -> None:
        from orchestrator.sdk_dispatch import SDKDispatcher
        # Pre-write iter-1 bundle with timing_observations
        (tmp_path / "runs" / "iter-1").mkdir(parents=True)
        bundle = _make_bundle(experiment_spec={
            "timing_observations": {
                "recommended_turn_silence_threshold_seconds": 360.0,
            },
        })
        (tmp_path / "runs" / "iter-1" / "bundle.yaml").write_text(
            yaml.safe_dump(bundle),
        )
        d = SDKDispatcher(
            work_dir=tmp_path, campaign=_campaign_with_default_threshold(tmp_path),
            sdk_runner=lambda **_: None,  # never called
        )
        # Asking about iter-2 → reads iter-1's bundle.
        v = d._bundle_recommended_turn_silence_threshold(2)
        assert v == 360.0

    def test_resolver_returns_none_for_iter_1(self, tmp_path: Path) -> None:
        """No prior iter exists for iter-1 → nothing to read."""
        from orchestrator.sdk_dispatch import SDKDispatcher
        d = SDKDispatcher(
            work_dir=tmp_path, campaign=_campaign_with_default_threshold(tmp_path),
            sdk_runner=lambda **_: None,
        )
        assert d._bundle_recommended_turn_silence_threshold(1) is None

    def test_resolver_returns_none_when_field_missing(self, tmp_path: Path) -> None:
        """Bundle exists but has no timing_observations.recommended."""
        from orchestrator.sdk_dispatch import SDKDispatcher
        (tmp_path / "runs" / "iter-1").mkdir(parents=True)
        # No timing_observations → falls through to None
        bundle = _make_bundle(experiment_spec={
            "verified_parameters": {"x": 1},
        })
        (tmp_path / "runs" / "iter-1" / "bundle.yaml").write_text(
            yaml.safe_dump(bundle),
        )
        d = SDKDispatcher(
            work_dir=tmp_path, campaign=_campaign_with_default_threshold(tmp_path),
            sdk_runner=lambda **_: None,
        )
        assert d._bundle_recommended_turn_silence_threshold(2) is None

    def test_dispatch_applies_bundle_override_then_restores(
            self, tmp_path: Path) -> None:
        """Behavioral: with an iter-1 bundle that recommends 100s, an
        iter-2 dispatch sees the 100s threshold flow to the runner.
        After the dispatch, the dispatcher's stored threshold returns
        to its campaign default — no leak into subsequent calls.
        """
        from orchestrator.sdk_dispatch import SDKDispatcher, SDKResult
        # iter-1 bundle: recommends 100s
        (tmp_path / "runs" / "iter-1").mkdir(parents=True)
        b1 = _make_bundle(experiment_spec={
            "timing_observations": {
                "recommended_turn_silence_threshold_seconds": 100.0,
            },
        })
        (tmp_path / "runs" / "iter-1" / "bundle.yaml").write_text(
            yaml.safe_dump(b1),
        )
        # iter-2 needs a problem.md / handoff.md for the LLMDispatcher
        # path — but SDKDispatcher just needs an output path.
        (tmp_path / "runs" / "iter-2").mkdir(parents=True)

        thresholds_seen: list[float | None] = []

        def runner(*, turn_silence_threshold=None, **_):
            thresholds_seen.append(turn_silence_threshold)
            return SDKResult(text="ok", input_tokens=1, output_tokens=1)

        d = SDKDispatcher(
            work_dir=tmp_path,
            campaign=_campaign_with_default_threshold(tmp_path),
            sdk_runner=runner,
            max_retries=0,
        )
        default_threshold = d._turn_silence_threshold  # campaign default

        # iter-2 dispatch: should see the bundle override (100.0)
        d.dispatch(
            "planner", "design",
            output_path=tmp_path / "runs" / "iter-2" / "design_log.md",
            iteration=2,
        )
        assert thresholds_seen == [100.0], (
            f"#226: iter-2 runner should see bundle override 100.0; "
            f"got {thresholds_seen!r}"
        )
        # Post-dispatch: dispatcher's stored threshold restored to default.
        assert d._turn_silence_threshold == default_threshold, (
            "#226: bundle override must NOT leak past the dispatch — "
            "next dispatch with no bundle override should see the "
            "campaign default again."
        )

    def test_dispatch_restores_threshold_when_runner_raises(
            self, tmp_path: Path,
            monkeypatch: pytest.MonkeyPatch) -> None:
        """#226 + post-PR-#227-review: the override-and-restore must
        survive a runner failure. If a regression moved the restore
        line out of ``finally``, this test catches it: dispatch() raises,
        but the dispatcher's stored threshold is still the campaign
        default — no leak into subsequent dispatches.
        """
        from orchestrator.sdk_dispatch import SDKDispatcher, SDKTransientError
        monkeypatch.setattr(
            "orchestrator.sdk_dispatch.time.sleep", lambda _s: None,
        )
        # iter-1 bundle: recommends 100s
        (tmp_path / "runs" / "iter-1").mkdir(parents=True)
        b1 = _make_bundle(experiment_spec={
            "timing_observations": {
                "recommended_turn_silence_threshold_seconds": 100.0,
            },
        })
        (tmp_path / "runs" / "iter-1" / "bundle.yaml").write_text(
            yaml.safe_dump(b1),
        )
        (tmp_path / "runs" / "iter-2").mkdir(parents=True)

        def runner(**_):
            raise SDKTransientError("simulated runner failure")

        d = SDKDispatcher(
            work_dir=tmp_path,
            campaign=_campaign_with_default_threshold(tmp_path),
            sdk_runner=runner,
            max_retries=0,
        )
        default_threshold = d._turn_silence_threshold

        with pytest.raises(RuntimeError):
            d.dispatch(
                "planner", "design",
                output_path=tmp_path / "runs" / "iter-2" / "design_log.md",
                iteration=2,
            )

        # Critical: post-failure, dispatcher's stored threshold MUST be
        # the campaign default — not the iter-1 override that was
        # applied transiently.
        assert d._turn_silence_threshold == default_threshold, (
            "post-PR-#227-review: try/finally must restore "
            "_turn_silence_threshold even when super().dispatch raises. "
            "A regression here would leak the override into all "
            "subsequent iterations of a long-running campaign."
        )

    def test_dispatch_uses_campaign_default_when_no_bundle_override(
            self, tmp_path: Path) -> None:
        """When the prior iter's bundle has no timing_observations,
        the campaign-level default is used unchanged."""
        from orchestrator.sdk_dispatch import SDKDispatcher, SDKResult
        (tmp_path / "runs" / "iter-1").mkdir(parents=True)
        b1 = _make_bundle()  # no experiment_spec at all
        (tmp_path / "runs" / "iter-1" / "bundle.yaml").write_text(
            yaml.safe_dump(b1),
        )
        (tmp_path / "runs" / "iter-2").mkdir(parents=True)

        thresholds_seen: list[float | None] = []

        def runner(*, turn_silence_threshold=None, **_):
            thresholds_seen.append(turn_silence_threshold)
            return SDKResult(text="ok", input_tokens=1, output_tokens=1)

        d = SDKDispatcher(
            work_dir=tmp_path,
            campaign=_campaign_with_default_threshold(tmp_path),
            sdk_runner=runner,
            max_retries=0,
        )
        d.dispatch(
            "planner", "design",
            output_path=tmp_path / "runs" / "iter-2" / "design_log.md",
            iteration=2,
        )
        # No bundle override → fall back to campaign default (600s).
        assert thresholds_seen == [600.0]


# ─── #223 v1: structured brief_amendments.jsonl schema + REPORT renderer ─


def _load_brief_amendments_schema() -> dict:
    return json.loads(
        (SCHEMAS_DIR / "brief_amendments.schema.json").read_text()
    )


class TestBriefAmendmentsSchema:
    """#223: structured brief_amendments.jsonl entries replace the prior
    free-form markdown so they can be programmatically parsed, applied,
    and propagated across campaign runs."""

    def _valid_amendment(self, **overrides) -> dict:
        a = {
            "id": "BA-1",
            "brief_section": "paper-burst-brief.md §ITER-1",
            "problem": "Probe command produces schema-invalid output",
            "fix": "Replace probe command with workload-spec version",
            "priority": "HIGH",
        }
        a.update(overrides)
        return a

    def test_minimal_amendment_validates(self):
        jsonschema.validate(self._valid_amendment(),
                            _load_brief_amendments_schema())

    def test_full_amendment_with_optional_fields_validates(self):
        a = self._valid_amendment(
            evidence="dropped_unservable=61, adversary completed=0",
            impact="iter-2 produces ground_truth_held=false trivially",
        )
        jsonschema.validate(a, _load_brief_amendments_schema())

    def test_id_pattern_enforced(self):
        for bad in ["1", "BA-", "BA-foo", "BA1", "ba-1"]:
            a = self._valid_amendment(id=bad)
            with pytest.raises(jsonschema.ValidationError):
                jsonschema.validate(a, _load_brief_amendments_schema())

    def test_priority_enum_enforced(self):
        for bad in ["URGENT", "blocking", "P0", "high", ""]:
            a = self._valid_amendment(priority=bad)
            with pytest.raises(jsonschema.ValidationError):
                jsonschema.validate(a, _load_brief_amendments_schema())

    def test_required_fields(self):
        for missing in ["id", "brief_section", "problem", "fix", "priority"]:
            a = self._valid_amendment()
            del a[missing]
            with pytest.raises(jsonschema.ValidationError):
                jsonschema.validate(a, _load_brief_amendments_schema())

    def test_unknown_field_rejected(self):
        a = self._valid_amendment(severity="high")  # typo for priority
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(a, _load_brief_amendments_schema())


from orchestrator.llm_dispatch import _format_brief_amendments_summary


class TestFormatBriefAmendmentsSummary:
    """The REPORT-context renderer produces a human/agent-readable
    summary grouped by priority."""

    def test_no_iter_dirs_returns_marker(self, tmp_path: Path) -> None:
        out = _format_brief_amendments_summary(tmp_path / "campaign")
        assert "no iteration directories" in out.lower()

    def test_no_amendments_returns_clean_marker(self, tmp_path: Path) -> None:
        wd = tmp_path / "campaign"
        (wd / "runs" / "iter-1" / "inputs").mkdir(parents=True)
        out = _format_brief_amendments_summary(wd)
        assert "no brief_amendments" in out.lower()

    def test_renders_amendments_grouped_by_priority(
            self, tmp_path: Path) -> None:
        wd = tmp_path / "campaign"
        inputs = wd / "runs" / "iter-1" / "inputs"
        inputs.mkdir(parents=True)
        rows = [
            {"id": "BA-1", "brief_section": "x §a", "problem": "low-pri thing",
             "fix": "fix-x", "priority": "LOW"},
            {"id": "BA-2", "brief_section": "x §b", "problem": "blocking gotcha",
             "fix": "fix-y", "priority": "BLOCKING"},
            {"id": "BA-3", "brief_section": "x §c", "problem": "medium concern",
             "fix": "fix-z", "priority": "MEDIUM"},
        ]
        (inputs / "brief_amendments.jsonl").write_text(
            "\n".join(json.dumps(r) for r in rows) + "\n"
        )
        out = _format_brief_amendments_summary(wd)
        assert "iter-1" in out
        assert "3 amendment(s)" in out
        # BLOCKING comes first (priority sort)
        blocking_idx = out.find("BA-2")
        low_idx = out.find("BA-1")
        medium_idx = out.find("BA-3")
        assert blocking_idx > 0 and low_idx > 0 and medium_idx > 0
        assert blocking_idx < medium_idx < low_idx, (
            "#223: amendments must be sorted BLOCKING > HIGH > MEDIUM > "
            "LOW > INFO so operators see the most urgent first."
        )

    def test_malformed_lines_surfaced(self, tmp_path: Path) -> None:
        """Malformed JSON lines are skipped but the count is surfaced —
        the operator must know corruption happened (mirroring the
        post-#218 bundle_amendments helper pattern)."""
        wd = tmp_path / "campaign"
        inputs = wd / "runs" / "iter-1" / "inputs"
        inputs.mkdir(parents=True)
        (inputs / "brief_amendments.jsonl").write_text(
            json.dumps({"id": "BA-1", "brief_section": "x", "problem": "p",
                        "fix": "f", "priority": "HIGH"}) + "\n"
            + "not valid json {\n"
            + "{garbage\n"
        )
        out = _format_brief_amendments_summary(wd)
        assert "BA-1" in out
        assert "malformed" in out.lower()
        assert "2 malformed" in out


class TestReportContextIncludesBriefAmendments:
    """#223: the REPORT extractor's prompt includes the brief_amendments
    summary so the report can describe what spec friction the campaign
    surfaced — not just narrate the experiment outcome."""

    def test_brief_amendments_appear_in_extractor_prompt(
            self, tmp_path: Path,
            monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        # Pre-create artifacts the report extractor reads.
        results = tmp_path / "runs" / "iter-1" / "results"
        results.mkdir(parents=True)
        (results / "h-main_seed42.json").write_text("{}")
        inputs = tmp_path / "runs" / "iter-1" / "inputs"
        inputs.mkdir(parents=True)
        (inputs / "brief_amendments.jsonl").write_text(json.dumps({
            "id": "BA-1",
            "brief_section": "paper-burst-brief.md §ITER-1",
            "problem": "missing --max-model-len 0 flag",
            "fix": "Add --max-model-len 0 to all main BLIS commands",
            "priority": "BLOCKING",
        }) + "\n")
        (tmp_path / "ledger.json").write_text(json.dumps({"iterations": []}))
        (tmp_path / "principles.json").write_text(json.dumps({"principles": []}))

        d = LLMDispatcher(
            work_dir=tmp_path,
            campaign=_make_campaign(),
            completion_fn=_make_completion(["# stub report"]),
        )
        d.dispatch(
            "extractor", "report",
            output_path=tmp_path / "report.md",
            iteration=0,
        )

        all_prompt = ""
        for call in d._completion.call_log:  # type: ignore[attr-defined]
            for msg in call.get("messages", []):
                all_prompt += msg.get("content", "") + "\n"

        assert "BA-1" in all_prompt, (
            "#223: REPORT extractor must see the structured "
            "brief_amendments — that's the cross-run-learning surface."
        )
        assert "BLOCKING" in all_prompt
        assert "max-model-len" in all_prompt


# ─── End-to-end coupling across #221+#222+#223+#224 ────────────────────────


from orchestrator.iteration_mode import iteration_mode_for, execute_mode_guidance_for
from orchestrator.promote_gate import evaluate_promote_gate


class TestEndToEndIntegration:
    """Post-PR-#227-review: a single test that exercises the chain
    #221 (mode signal flows to EXECUTE) → #222 (rehearsal_subset is the
    structural scope) → #223 (BLOCKING brief_amendment is written by
    rehearsal) → #224 (gate decides revise based on it).

    If any link in the chain breaks (mode resolver bug, schema drift,
    field-name typo, gate logic regression), this test catches it
    even though each per-feature test still passes."""

    def test_rehearsal_emits_blocking_amendment_then_gate_revises(
            self, tmp_path: Path) -> None:
        # 1. Campaign declares iter-1 rehearsal, iter-2 real (#212).
        c = _make_campaign()
        c["iterations"] = [{"mode": "rehearsal"}, {"mode": "real"}]

        # 2. Mode resolver returns "rehearsal" for iter-1 (#212).
        assert iteration_mode_for(c, 1) == "rehearsal"
        assert iteration_mode_for(c, 2) == "real"

        # 3. Execute-phase guidance for rehearsal mentions
        # rehearsal_subset (#221 → #222 link).
        guidance = execute_mode_guidance_for("rehearsal")
        assert "rehearsal_subset" in guidance, (
            "#221 → #222 link broken: execute-phase rehearsal guidance "
            "must reference rehearsal_subset (the structural scope)."
        )
        # And mentions the brief_amendments.jsonl path (#221 → #223 link).
        assert "brief_amendments.jsonl" in guidance
        assert "BLOCKING" in guidance

        # 4. DESIGN agent emits a bundle with rehearsal_subset (#222).
        # Schema-validate to confirm the structural field is honored.
        bundle = _make_bundle(experiment_spec={
            "rehearsal_subset": {
                "seeds": [42],
                "arms": ["h-main", "h-control-negative"],
                "extra_validation_only": True,
            },
        })
        jsonschema.validate(bundle, _load_bundle_schema())

        # 5. Rehearsal iter-1 emits a BLOCKING brief_amendment (#223
        # structured form). Schema-validate the amendment row.
        iter1 = tmp_path / "runs" / "iter-1"
        inputs = iter1 / "inputs"
        inputs.mkdir(parents=True)
        amendment = {
            "id": "BA-1",
            "brief_section": "paper-burst-brief.md §ITER-1",
            "problem": "Probe command produces schema-invalid output",
            "fix": "Replace probe command with workload-spec version",
            "priority": "BLOCKING",
        }
        jsonschema.validate(amendment, _load_brief_amendments_schema())
        (inputs / "brief_amendments.jsonl").write_text(
            json.dumps(amendment) + "\n"
        )
        # Plus a successful findings.json so the gate passes its
        # apparatus check.
        (iter1 / "findings.json").write_text(json.dumps({
            "iteration": 1,
            "bundle_ref": "runs/iter-1/bundle.yaml",
            "experiment_valid": True,
            "arms": [{
                "arm_type": "h-main",
                "predicted": "stub", "observed": "stub",
                "status": "CONFIRMED", "error_type": None,
                "diagnostic_note": "stub",
            }],
        }))

        # 6. Promote gate (#224) decides revise — because BA-1 is
        # BLOCKING and applied_amendments.jsonl is empty.
        result = evaluate_promote_gate(tmp_path, 1)
        assert result["decision"] == "revise", (
            "#224 link broken: gate must emit revise when a BLOCKING "
            f"amendment is unapplied. Got {result!r}"
        )
        assert "BA-1" in result["blocking_amendments"]
        # Reasoning string is operator-actionable.
        assert "BA-1" in result["reasoning"]

        # 7. Operator applies BA-1 → applied_amendments.jsonl populated
        # → gate now promotes. (In v2 this is a CLI; in v1 it's manual.)
        (tmp_path / "applied_amendments.jsonl").write_text(
            json.dumps({"id": "BA-1"}) + "\n"
        )
        result_after = evaluate_promote_gate(tmp_path, 1)
        assert result_after["decision"] == "promote", (
            "#224 link: once the BLOCKING amendment is in "
            "applied_amendments.jsonl, the gate should promote."
        )
        assert "BA-1" in result_after["applied_amendments"]
