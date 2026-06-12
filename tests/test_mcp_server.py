"""Behavioral tests for the nous-mcp stdio server (#126 Phase B).

The MCP server is a thin wrapper around campaign_index. Tests drive
``handle_request`` directly with JSON-RPC payloads (no real stdio) and
assert what comes back. This is the contract any MCP client sees.
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
from pathlib import Path


HOOK_PATH = Path(__file__).resolve().parent.parent / "bin" / "nous-mcp"


def _load_module():
    loader = importlib.machinery.SourceFileLoader("nous_mcp", str(HOOK_PATH))
    spec = importlib.util.spec_from_loader("nous_mcp", loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def _make_campaign(root: Path, run_id: str, *, principles: list[dict] | None = None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "state.json").write_text(json.dumps({
        "run_id": run_id, "phase": "DONE", "iteration": 2,
    }))
    (root / "ledger.json").write_text(json.dumps({
        "iterations": [{"iteration": 1}, {"iteration": 2}],
    }))
    (root / "principles.json").write_text(json.dumps({
        "principles": principles or [],
    }))
    return root


# ─── initialize / capabilities ─────────────────────────────────────────────


class TestInitialize:

    def test_initialize_returns_protocol_and_capabilities(self):
        mod = _load_module()
        resp = mod.handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize"})

        assert resp["jsonrpc"] == "2.0"
        assert resp["id"] == 1
        assert "result" in resp
        result = resp["result"]
        assert "protocolVersion" in result
        assert result["serverInfo"]["name"] == "nous-mcp"
        assert "resources" in result["capabilities"]
        assert "tools" in result["capabilities"]

    def test_unknown_method_returns_jsonrpc_error(self):
        mod = _load_module()
        resp = mod.handle_request({
            "jsonrpc": "2.0", "id": 9, "method": "garbage",
        })
        assert resp["error"]["code"] == -32601
        assert "garbage" in resp["error"]["message"]


# ─── resources ─────────────────────────────────────────────────────────────


class TestResources:

    def test_list_includes_campaigns_root_and_per_campaign_resources(self, tmp_path):
        repo = tmp_path / "repo"
        _make_campaign(repo / ".nous" / "alpha", "alpha")
        _make_campaign(repo / ".nous" / "beta", "beta")

        mod = _load_module()
        resp = mod.handle_request(
            {"jsonrpc": "2.0", "id": 2, "method": "resources/list"},
            search_root=str(tmp_path),
        )

        uris = [r["uri"] for r in resp["result"]["resources"]]
        assert "nous://campaigns" in uris
        assert "nous://campaigns/alpha/state" in uris
        assert "nous://campaigns/alpha/principles" in uris
        assert "nous://campaigns/beta/state" in uris

    def test_read_state_returns_state_json_contents(self, tmp_path):
        _make_campaign(tmp_path / "repo" / ".nous" / "x", "x")

        mod = _load_module()
        resp = mod.handle_request(
            {
                "jsonrpc": "2.0", "id": 3, "method": "resources/read",
                "params": {"uri": "nous://campaigns/x/state"},
            },
            search_root=str(tmp_path),
        )

        body = json.loads(resp["result"]["contents"][0]["text"])
        assert body["run_id"] == "x"
        assert body["phase"] == "DONE"

    def test_read_principles_returns_principles_json(self, tmp_path):
        _make_campaign(
            tmp_path / "repo" / ".nous" / "x", "x",
            principles=[{"id": "p1", "status": "active", "statement": "..."}],
        )

        mod = _load_module()
        resp = mod.handle_request(
            {
                "jsonrpc": "2.0", "id": 4, "method": "resources/read",
                "params": {"uri": "nous://campaigns/x/principles"},
            },
            search_root=str(tmp_path),
        )

        body = json.loads(resp["result"]["contents"][0]["text"])
        assert any(p["id"] == "p1" for p in body["principles"])

    def test_read_unknown_campaign_returns_error(self, tmp_path):
        mod = _load_module()
        resp = mod.handle_request(
            {
                "jsonrpc": "2.0", "id": 5, "method": "resources/read",
                "params": {"uri": "nous://campaigns/nonexistent/state"},
            },
            search_root=str(tmp_path),
        )
        assert "error" in resp
        assert "nonexistent" in resp["error"]["message"]


# ─── tools ─────────────────────────────────────────────────────────────────


class TestTools:

    def test_list_returns_four_tools(self):
        mod = _load_module()
        resp = mod.handle_request(
            {"jsonrpc": "2.0", "id": 6, "method": "tools/list"},
        )
        names = [t["name"] for t in resp["result"]["tools"]]
        assert "nous.list_campaigns" in names
        assert "nous.search_principles" in names
        assert "nous.get_arm_results" in names
        assert "nous.compare_iterations" in names

    def test_call_list_campaigns_returns_summaries(self, tmp_path):
        _make_campaign(tmp_path / "repo" / ".nous" / "alpha", "alpha")

        mod = _load_module()
        resp = mod.handle_request(
            {
                "jsonrpc": "2.0", "id": 7, "method": "tools/call",
                "params": {
                    "name": "nous.list_campaigns",
                    "arguments": {"search_root": str(tmp_path)},
                },
            },
        )
        body = json.loads(resp["result"]["content"][0]["text"])
        assert any(c["run_id"] == "alpha" for c in body["campaigns"])

    def test_call_search_principles_finds_known_substring(self, tmp_path):
        _make_campaign(
            tmp_path / "repo" / ".nous" / "x", "x",
            principles=[{
                "id": "p1", "status": "active",
                "statement": "Saturation flattens discriminatory power.",
            }],
        )

        mod = _load_module()
        resp = mod.handle_request(
            {
                "jsonrpc": "2.0", "id": 8, "method": "tools/call",
                "params": {
                    "name": "nous.search_principles",
                    "arguments": {
                        "search_root": str(tmp_path),
                        "text": "saturation",
                    },
                },
            },
        )
        body = json.loads(resp["result"]["content"][0]["text"])
        assert len(body["hits"]) == 1
        assert body["hits"][0]["principle"]["id"] == "p1"

    def test_call_unknown_tool_returns_error(self):
        mod = _load_module()
        resp = mod.handle_request({
            "jsonrpc": "2.0", "id": 10, "method": "tools/call",
            "params": {"name": "nous.delete_campaign", "arguments": {}},
        })
        assert "error" in resp
        assert "delete_campaign" in resp["error"]["message"]


# ─── error handling ────────────────────────────────────────────────────────


class TestErrorHandling:

    def test_missing_required_arg_returns_jsonrpc_error_not_crash(self):
        mod = _load_module()
        resp = mod.handle_request({
            "jsonrpc": "2.0", "id": 11, "method": "tools/call",
            "params": {
                "name": "nous.compare_iterations",
                "arguments": {"campaign_root": "/nope"},  # missing iter_a, iter_b
            },
        })
        assert "error" in resp
