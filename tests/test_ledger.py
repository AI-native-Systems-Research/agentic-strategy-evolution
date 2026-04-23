"""Tests for the deterministic ledger append module."""
import json

import jsonschema
import yaml

from orchestrator.ledger import append_ledger_row


SCHEMAS_DIR = __import__("pathlib").Path(__file__).resolve().parent.parent / "schemas"


def _load_schema(name: str) -> dict:
    path = SCHEMAS_DIR / name
    if path.suffix in (".yaml", ".yml"):
        return yaml.safe_load(path.read_text())
    return json.loads(path.read_text())


def _write_bundle(iter_dir, iteration=1, family="test-family"):
    bundle = {
        "metadata": {
            "iteration": iteration,
            "family": family,
            "research_question": "Does X affect Y?",
        },
        "arms": [
            {
                "type": "h-main",
                "prediction": "Y increases by 10%",
                "mechanism": "X causes Y",
                "diagnostic": "Check X->Y path",
            },
            {
                "type": "h-control-negative",
                "prediction": "no effect without X",
                "mechanism": "no X means no Y change",
                "diagnostic": "verify baseline",
            },
        ],
    }
    iter_dir.mkdir(parents=True, exist_ok=True)
    (iter_dir / "bundle.yaml").write_text(
        yaml.safe_dump(bundle, default_flow_style=False, sort_keys=False)
    )


def _write_findings(iter_dir, iteration=1, h_main="CONFIRMED", control="CONFIRMED"):
    findings = {
        "iteration": iteration,
        "bundle_ref": f"runs/iter-{iteration}/bundle.yaml",
        "arms": [
            {
                "arm_type": "h-main",
                "predicted": "Y increases by 10%",
                "observed": "Y increased by 12%",
                "status": h_main,
                "error_type": None if h_main == "CONFIRMED" else "direction",
                "diagnostic_note": None,
            },
            {
                "arm_type": "h-control-negative",
                "predicted": "no effect without X",
                "observed": "no significant change",
                "status": control,
                "error_type": None,
                "diagnostic_note": None,
            },
        ],
        "discrepancy_analysis": "All arms within expected range.",
    }
    (iter_dir / "findings.json").write_text(json.dumps(findings, indent=2))


def _write_principles(work_dir, principles_list):
    (work_dir / "principles.json").write_text(
        json.dumps({"principles": principles_list}, indent=2)
    )


class TestAppendLedgerRow:
    def test_append_basic(self, tmp_path):
        iter_dir = tmp_path / "runs" / "iter-1"
        _write_bundle(iter_dir)
        _write_findings(iter_dir)
        _write_principles(tmp_path, [
            {
                "id": "P-1",
                "statement": "X causes Y",
                "confidence": "medium",
                "regime": "all",
                "evidence": ["iteration-1-h-main"],
                "contradicts": [],
                "extraction_iteration": 1,
                "mechanism": "direct causation",
                "applicability_bounds": "when X present",
                "superseded_by": None,
                "category": "domain",
                "status": "active",
            }
        ])

        append_ledger_row(tmp_path, 1)

        ledger = json.loads((tmp_path / "ledger.json").read_text())
        jsonschema.validate(ledger, _load_schema("ledger.schema.json"))
        assert len(ledger["iterations"]) == 1
        row = ledger["iterations"][0]
        assert row["iteration"] == 1
        assert row["family"] == "test-family"
        assert row["h_main_result"] == "CONFIRMED"
        assert row["control_result"] == "CONFIRMED"
        assert row["prediction_accuracy"]["arms_correct"] == 2
        assert row["prediction_accuracy"]["arms_total"] == 2
        assert row["prediction_accuracy"]["accuracy_pct"] == 100.0
        assert len(row["principles_extracted"]) == 1
        assert row["principles_extracted"][0] == {"id": "P-1", "action": "INSERT"}

    def test_append_no_findings_is_noop(self, tmp_path):
        iter_dir = tmp_path / "runs" / "iter-1"
        iter_dir.mkdir(parents=True)
        _write_bundle(iter_dir)
        # No findings.json

        append_ledger_row(tmp_path, 1)

        assert not (tmp_path / "ledger.json").exists()

    def test_append_preserves_existing(self, tmp_path):
        # Pre-populate ledger with baseline row
        ledger = {
            "iterations": [
                {
                    "iteration": 0,
                    "family": "baseline",
                    "timestamp": "1970-01-01T00:00:00Z",
                    "candidate_id": "baseline",
                    "h_main_result": None,
                    "ablation_results": {},
                    "control_result": None,
                    "robustness_result": None,
                    "prediction_accuracy": None,
                    "principles_extracted": [],
                    "frontier_update": None,
                }
            ]
        }
        (tmp_path / "ledger.json").write_text(json.dumps(ledger, indent=2))

        iter_dir = tmp_path / "runs" / "iter-1"
        _write_bundle(iter_dir)
        _write_findings(iter_dir)
        _write_principles(tmp_path, [])

        append_ledger_row(tmp_path, 1)

        result = json.loads((tmp_path / "ledger.json").read_text())
        jsonschema.validate(result, _load_schema("ledger.schema.json"))
        assert len(result["iterations"]) == 2
        assert result["iterations"][0]["family"] == "baseline"
        assert result["iterations"][1]["family"] == "test-family"

    def test_prediction_accuracy(self, tmp_path):
        iter_dir = tmp_path / "runs" / "iter-1"
        _write_bundle(iter_dir)
        _write_findings(iter_dir, h_main="REFUTED", control="CONFIRMED")
        _write_principles(tmp_path, [])

        append_ledger_row(tmp_path, 1)

        ledger = json.loads((tmp_path / "ledger.json").read_text())
        row = ledger["iterations"][0]
        assert row["h_main_result"] == "REFUTED"
        assert row["prediction_accuracy"]["arms_correct"] == 1
        assert row["prediction_accuracy"]["arms_total"] == 2
        assert row["prediction_accuracy"]["accuracy_pct"] == 50.0

    def test_ablation_results_collected(self, tmp_path):
        iter_dir = tmp_path / "runs" / "iter-1"
        _write_bundle(iter_dir)
        # Findings with ablation arms
        findings = {
            "iteration": 1,
            "bundle_ref": "runs/iter-1/bundle.yaml",
            "arms": [
                {
                    "arm_type": "h-main",
                    "predicted": "p", "observed": "o",
                    "status": "CONFIRMED",
                    "error_type": None, "diagnostic_note": None,
                },
                {
                    "arm_type": "h-ablation",
                    "predicted": "p", "observed": "o",
                    "status": "REFUTED",
                    "error_type": "direction", "diagnostic_note": None,
                },
                {
                    "arm_type": "h-control-negative",
                    "predicted": "p", "observed": "o",
                    "status": "CONFIRMED",
                    "error_type": None, "diagnostic_note": None,
                },
            ],
            "discrepancy_analysis": "Ablation refuted.",
        }
        (iter_dir / "findings.json").write_text(json.dumps(findings, indent=2))
        _write_principles(tmp_path, [])

        append_ledger_row(tmp_path, 1)

        ledger = json.loads((tmp_path / "ledger.json").read_text())
        jsonschema.validate(ledger, _load_schema("ledger.schema.json"))
        row = ledger["iterations"][0]
        assert row["ablation_results"] == {"ablation-0": "REFUTED"}

    def test_no_principles_file_handled(self, tmp_path):
        iter_dir = tmp_path / "runs" / "iter-1"
        _write_bundle(iter_dir)
        _write_findings(iter_dir)
        # No principles.json

        append_ledger_row(tmp_path, 1)

        ledger = json.loads((tmp_path / "ledger.json").read_text())
        jsonschema.validate(ledger, _load_schema("ledger.schema.json"))
        assert ledger["iterations"][0]["principles_extracted"] == []

    def test_idempotent_no_duplicate(self, tmp_path):
        iter_dir = tmp_path / "runs" / "iter-1"
        _write_bundle(iter_dir)
        _write_findings(iter_dir)
        _write_principles(tmp_path, [])

        append_ledger_row(tmp_path, 1)
        append_ledger_row(tmp_path, 1)  # Second call for same iteration

        ledger = json.loads((tmp_path / "ledger.json").read_text())
        assert len(ledger["iterations"]) == 1

    def test_no_bundle_still_works(self, tmp_path):
        iter_dir = tmp_path / "runs" / "iter-1"
        iter_dir.mkdir(parents=True)
        _write_findings(iter_dir)
        _write_principles(tmp_path, [])
        # No bundle.yaml — family defaults to "unknown"

        append_ledger_row(tmp_path, 1)

        ledger = json.loads((tmp_path / "ledger.json").read_text())
        jsonschema.validate(ledger, _load_schema("ledger.schema.json"))
        assert ledger["iterations"][0]["family"] == "unknown"
