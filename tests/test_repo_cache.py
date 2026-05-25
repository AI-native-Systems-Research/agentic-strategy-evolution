"""Behavioral tests for the repo-level knowledge cache (issue #156).

Tests assert what's on disk after write_repo_cache + read_repo_cache,
not which internal helpers were called. Per CLAUDE.md, no live LLM
calls; freshness is exercised by injecting a deterministic
``head_sha_fn`` instead of relying on real git state.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

from orchestrator.repo_cache import (
    RepoCache,
    build_cache_from_campaign,
    cache_dir_for,
    is_fresh,
    read_repo_cache,
    render_cache_for_design_prompt,
    write_repo_cache,
)


# ─── Round-trip ────────────────────────────────────────────────────────────


class TestRoundTrip:
    """write → read should preserve the cache content."""

    def test_full_cache_round_trips(self, tmp_path: Path) -> None:
        sha_fn = lambda _: "abc123"

        write_repo_cache(
            tmp_path,
            exploration="# Repo tour\n\nThe `core/` package owns scheduling.\n",
            knobs=[
                {"name": "batch_size", "location": "src/sched.go:42",
                 "type": "int", "default": 32, "range": [1, 128]},
                {"name": "preempt", "type": "bool", "default": False},
            ],
            metrics=[
                {"name": "latency_ms", "unit": "ms",
                 "capture": "stdout JSON 'latency_ms'"},
            ],
            build={
                "build_command": "make build",
                "test_command": "make test",
                "prerequisites": ["go 1.21+"],
            },
            head_sha_fn=sha_fn,
        )

        cache = read_repo_cache(tmp_path, head_sha_fn=sha_fn)
        assert cache is not None
        assert cache.fresh is True
        assert cache.verified_sha == "abc123"
        assert cache.head_sha == "abc123"
        assert "core/" in cache.exploration
        assert {k["name"] for k in cache.knobs} == {"batch_size", "preempt"}
        assert cache.metrics[0]["capture"].startswith("stdout JSON")
        assert cache.build["build_command"] == "make build"
        assert "go 1.21+" in cache.build["prerequisites"]

    def test_partial_cache_round_trips(self, tmp_path: Path) -> None:
        """Writing only exploration is valid — knobs/metrics/build optional."""
        write_repo_cache(
            tmp_path,
            exploration="# tour\nshort\n",
            head_sha_fn=lambda _: "deadbeef",
        )
        cache = read_repo_cache(tmp_path, head_sha_fn=lambda _: "deadbeef")
        assert cache is not None
        assert "tour" in cache.exploration
        assert cache.knobs == []
        assert cache.metrics == []
        assert cache.build == {}

    def test_disk_layout_matches_documented_paths(self, tmp_path: Path) -> None:
        write_repo_cache(
            tmp_path,
            exploration="x",
            knobs=[{"name": "k1"}],
            metrics=[{"name": "m1"}],
            build={"build_command": "echo build"},
            head_sha_fn=lambda _: "sha1",
        )
        cache_dir = cache_dir_for(tmp_path)
        assert (cache_dir / "exploration.md").exists()
        assert (cache_dir / "knobs.yaml").exists()
        assert (cache_dir / "metrics.yaml").exists()
        assert (cache_dir / "build.yaml").exists()
        assert (cache_dir / "schema_version.txt").exists()
        assert (cache_dir / "last_verified_at.txt").exists()
        # Verify on-disk yaml shape too
        knobs_content = yaml.safe_load((cache_dir / "knobs.yaml").read_text())
        assert knobs_content["schema_version"] == "1"
        assert knobs_content["knobs"] == [{"name": "k1"}]


# ─── Freshness ────────────────────────────────────────────────────────────


class TestFreshness:
    """fresh=True only when verified_sha == HEAD."""

    def test_matching_sha_is_fresh(self, tmp_path: Path) -> None:
        write_repo_cache(tmp_path, exploration="x", head_sha_fn=lambda _: "abc")
        assert is_fresh(tmp_path, head_sha_fn=lambda _: "abc")

    def test_diverged_sha_is_stale(self, tmp_path: Path) -> None:
        write_repo_cache(tmp_path, exploration="x", head_sha_fn=lambda _: "abc")
        assert not is_fresh(tmp_path, head_sha_fn=lambda _: "xyz")

    def test_unknown_sha_is_stale(self, tmp_path: Path) -> None:
        """Cache written without git is conservatively never fresh."""
        write_repo_cache(tmp_path, exploration="x", head_sha_fn=lambda _: None)
        assert not is_fresh(tmp_path, head_sha_fn=lambda _: None)
        # Even if we now claim a sha, the cache file says "unknown" so it
        # cannot equal the new HEAD.
        assert not is_fresh(tmp_path, head_sha_fn=lambda _: "abc")

    def test_missing_cache_returns_none(self, tmp_path: Path) -> None:
        assert read_repo_cache(tmp_path) is None
        assert not is_fresh(tmp_path)


# ─── Corruption resilience ────────────────────────────────────────────────


class TestCorruptionResilience:
    """A malformed file shouldn't crash the reader."""

    def test_invalid_yaml_in_knobs_drops_knobs(self, tmp_path: Path) -> None:
        write_repo_cache(
            tmp_path, exploration="x", knobs=[{"name": "k"}],
            head_sha_fn=lambda _: "sha",
        )
        (cache_dir_for(tmp_path) / "knobs.yaml").write_text("not: [valid yaml: ][")
        cache = read_repo_cache(tmp_path, head_sha_fn=lambda _: "sha")
        assert cache is not None
        assert cache.knobs == []  # corrupt → empty, not crash
        assert cache.exploration == "x"  # other files survive

    def test_schema_violation_in_metrics_drops_metrics(self, tmp_path: Path) -> None:
        write_repo_cache(
            tmp_path, exploration="x", metrics=[{"name": "m"}],
            head_sha_fn=lambda _: "sha",
        )
        # Write a metrics.yaml that violates schema (missing schema_version).
        (cache_dir_for(tmp_path) / "metrics.yaml").write_text(
            yaml.safe_dump({"metrics": [{"name": "still here"}]})
        )
        cache = read_repo_cache(tmp_path, head_sha_fn=lambda _: "sha")
        assert cache is not None
        assert cache.metrics == []


# ─── Markdown rendering ───────────────────────────────────────────────────


class TestRenderForPrompt:
    def test_fresh_cache_renders_full_block(self, tmp_path: Path) -> None:
        write_repo_cache(
            tmp_path,
            exploration="# tour\nthe sched is in core/\n",
            knobs=[{"name": "batch_size", "location": "src/sched.go:42",
                    "type": "int"}],
            metrics=[{"name": "latency_ms", "unit": "ms",
                      "capture": "stdout JSON"}],
            build={"build_command": "make build", "test_command": "make test",
                   "prerequisites": ["go 1.21+"]},
            head_sha_fn=lambda _: "x",
        )
        cache = read_repo_cache(tmp_path, head_sha_fn=lambda _: "x")
        assert cache is not None
        rendered = render_cache_for_design_prompt(cache)
        assert "## Repo cache" in rendered
        assert "batch_size" in rendered
        assert "src/sched.go:42" in rendered
        assert "latency_ms" in rendered
        assert "make build" in rendered

    def test_stale_cache_renders_empty(self, tmp_path: Path) -> None:
        write_repo_cache(tmp_path, exploration="x", head_sha_fn=lambda _: "old")
        cache = read_repo_cache(tmp_path, head_sha_fn=lambda _: "new")
        assert cache is not None
        assert cache.fresh is False
        # Even with content, stale cache renders nothing — caller should
        # fall back to today's behavior.
        assert render_cache_for_design_prompt(cache) == ""

    def test_empty_cache_renders_empty(self) -> None:
        assert render_cache_for_design_prompt(RepoCache(fresh=True)) == ""


# ─── Heuristic builder from campaign artifacts ────────────────────────────


class TestBuildFromCampaign:
    def test_extracts_handoff_into_exploration(self, tmp_path: Path) -> None:
        work_dir = tmp_path / "campaign"
        work_dir.mkdir()
        (work_dir / "handoff.md").write_text(
            "## Handoff\n\n"
            "### Goal\n\n"
            "Test the mechanism\n\n"
            "### System Interface\n\n"
            "- **Build:** `make build`\n"
            "- **Run baseline:** `./bin/sim --config small.yaml`\n"
        )
        campaign = {
            "target_system": {
                "observable_metrics": ["latency_ms", "qps"],
                "controllable_knobs": ["batch_size"],
            }
        }

        exploration, knobs, metrics, build = build_cache_from_campaign(
            work_dir, campaign,
        )

        assert "Goal" in exploration
        assert "System Interface" in exploration
        assert {k["name"] for k in knobs} == {"batch_size"}
        assert {m["name"] for m in metrics} == {"latency_ms", "qps"}
        assert build.get("build_command") == "make build"
        assert "./bin/sim --config small.yaml" in build.get("run_command", "")

    def test_empty_campaign_yields_empty_cache(self, tmp_path: Path) -> None:
        work_dir = tmp_path / "campaign"
        work_dir.mkdir()
        exploration, knobs, metrics, build = build_cache_from_campaign(
            work_dir, {},
        )
        assert exploration == ""
        assert knobs == []
        assert metrics == []
        assert build == {}


# ─── End-to-end behavioral: two-campaign cache reuse ──────────────────────


class TestTwoCampaignReuse:
    """Simulate two campaigns on the same repo. The second sees a fresh cache."""

    def test_second_campaign_sees_first_campaigns_cache(self, tmp_path: Path) -> None:
        repo = tmp_path / "fake_repo"
        repo.mkdir()
        sha = "first-campaign-sha"

        # ─ First campaign: produces a handoff.md + writes cache at end.
        first_work = repo / ".nous" / "first-run"
        first_work.mkdir(parents=True)
        (first_work / "handoff.md").write_text(
            "## Handoff\n\n"
            "### Goal\n\nLearn the system.\n\n"
            "### System Interface\n\n"
            "- **Build:** `cargo build --release`\n"
        )
        campaign_yaml = {
            "target_system": {
                "repo_path": str(repo),
                "observable_metrics": ["throughput"],
                "controllable_knobs": ["workers"],
            }
        }
        exploration, knobs, metrics, build = build_cache_from_campaign(
            first_work, campaign_yaml,
        )
        write_repo_cache(
            repo, exploration=exploration, knobs=knobs, metrics=metrics,
            build=build, head_sha_fn=lambda _: sha,
        )

        # ─ Second campaign reads the cache before doing anything.
        cache = read_repo_cache(repo, head_sha_fn=lambda _: sha)
        assert cache is not None
        assert cache.fresh is True
        assert "Goal" in cache.exploration
        assert {k["name"] for k in cache.knobs} == {"workers"}
        assert cache.build["build_command"] == "cargo build --release"

        rendered = render_cache_for_design_prompt(cache)
        # The rendered block is what would feed the planner — verify the
        # second campaign's design phase has cheap access to first
        # campaign's facts.
        assert "cargo build --release" in rendered
        assert "workers" in rendered

    def test_repo_evolves_cache_becomes_stale(self, tmp_path: Path) -> None:
        """When HEAD diverges, the cache is marked stale; second campaign
        must fall back to fresh exploration."""
        repo = tmp_path / "fake_repo"
        repo.mkdir()

        write_repo_cache(
            repo, exploration="# old tour\n",
            head_sha_fn=lambda _: "old-sha",
        )

        # Time passes, repo evolves.
        cache = read_repo_cache(repo, head_sha_fn=lambda _: "new-sha")
        assert cache is not None
        assert cache.fresh is False
        # The renderer protects callers that forget to check fresh.
        assert render_cache_for_design_prompt(cache) == ""


# ─── Real-git smoke test (uses a tiny initialised repo) ───────────────────


class TestRealGit:
    """One light test against an actual `git init` repo to exercise the
    default head_sha_fn path. Most tests use injected fakes."""

    def test_real_git_repo_freshness(self, tmp_path: Path) -> None:
        repo = tmp_path / "real_repo"
        repo.mkdir()
        try:
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
            (repo / "README.md").write_text("hi\n")
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
        except (FileNotFoundError, subprocess.CalledProcessError) as e:
            pytest.skip(f"git not available: {e}")

        write_repo_cache(repo, exploration="# tour\n")
        assert is_fresh(repo)

        # New commit changes HEAD, cache becomes stale.
        (repo / "README.md").write_text("changed\n")
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "change"], cwd=repo, check=True)
        assert not is_fresh(repo)
