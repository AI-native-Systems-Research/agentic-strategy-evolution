"""Tests for template conformance to schemas."""
import jsonschema


class TestTemplateConformance:
    def test_state_template_conforms(self, load_schema, load_template):
        schema = load_schema("state.schema.json")
        template = load_template("state.json")
        jsonschema.validate(template, schema)

    def test_ledger_template_conforms(self, load_schema, load_template):
        schema = load_schema("ledger.schema.json")
        template = load_template("ledger.json")
        jsonschema.validate(template, schema)

    def test_principles_template_conforms(self, load_schema, load_template):
        schema = load_schema("principles.schema.json")
        template = load_template("principles.json")
        jsonschema.validate(template, schema)

    def test_bundle_template_conforms(self, load_schema, load_template):
        schema = load_schema("bundle.schema.yaml")
        template = load_template("bundle.yaml")
        jsonschema.validate(template, schema)

    def test_state_template_is_init(self, load_template):
        t = load_template("state.json")
        assert t["phase"] == "INIT"
        assert t["iteration"] == 0
        assert t["config_ref"] is None

    def test_ledger_template_has_baseline(self, load_template):
        t = load_template("ledger.json")
        assert len(t["iterations"]) == 1
        assert t["iterations"][0]["iteration"] == 0
        assert t["iterations"][0]["candidate_id"] == "baseline"

    def test_principles_template_is_empty(self, load_template):
        t = load_template("principles.json")
        assert t["principles"] == []

    def test_problem_template_exists(self, templates_dir):
        assert (templates_dir / "problem.md").exists()
        content = (templates_dir / "problem.md").read_text()
        assert "Research Question" in content
        assert "Baseline" in content
        assert "Success Criteria" in content
        assert "Experimental Conditions" in content

    def test_campaign_template_conforms(self, load_schema, load_template):
        schema = load_schema("campaign.schema.yaml")
        template = load_template("campaign.yaml")
        jsonschema.validate(template, schema)

    def test_campaign_template_has_defaults(self, load_template):
        t = load_template("campaign.yaml")
        assert len(t["review"]["design_perspectives"]) == 5
        assert len(t["review"]["findings_perspectives"]) == 10
        assert t["review"]["max_review_rounds"] == 10
        assert t["prompts"]["domain_adapter_layer"] is None

    def test_findings_template_conforms(self, load_schema, load_template):
        schema = load_schema("findings.schema.json")
        template = load_template("findings.json")
        jsonschema.validate(template, schema)
        assert template["iteration"] == 0
        assert len(template["arms"]) >= 1
