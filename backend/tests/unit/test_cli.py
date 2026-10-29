"""In-process CLI tests (cli.py must not stay at 0% coverage).

The CLI is exercised via cli.main() with AGENTBOUNDARY_DB_PATH pointed at a
tmp database, so no demo DB is touched. The subprocess weak-mode tests in
tests/evaluation/test_scenarios.py still cover the subprocess path.
"""

import glob
import json
import os
import tempfile

import pytest

from agentboundary.cli import main


@pytest.fixture()
def cli_env(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTBOUNDARY_DB_PATH", str(tmp_path / "cli.db"))
    monkeypatch.delenv("AGENTBOUNDARY_UNSAFE_LAB", raising=False)
    return tmp_path


def test_cli_seed_reset_run_run_all(cli_env, capsys):
    assert main(["seed"]) == 0
    assert "records" in capsys.readouterr().out
    assert main(["reset"]) == 0
    capsys.readouterr()  # clear the reset line before parsing run JSON
    assert main(["run", "--scenario", "A1"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["scenario_id"] == "A1" and out["verdict"] == "PASS"
    assert out["operator_persona_id"] == "cli"
    assert main(["run-all"]) == 0
    summaries = json.loads(capsys.readouterr().out)
    assert [s["scenario_id"] for s in summaries] == [
        "A1",
        "A2",
        "A3",
        "A4",
        "A5",
        "A6",
    ]
    assert all(s["verdict"] == "PASS" for s in summaries)


def test_cli_unknown_scenario(cli_env):
    assert main(["run", "--scenario", "A9"]) == 2


def test_cli_weak_env_gate_and_cleanup(cli_env, monkeypatch, capsys):
    assert main(["run-weak", "--scenario", "A2"]) == 2
    monkeypatch.setenv("AGENTBOUNDARY_UNSAFE_LAB", "1")
    before = set(
        glob.glob(os.path.join(tempfile.gettempdir(), "agentboundary-weak-*.db"))
    )
    out = cli_env / "weak.json"
    assert main(["run-weak", "--scenario", "A2", "--out", str(out)]) == 0
    data = json.loads(out.read_text())
    assert data["mode"] == "weak" and data["run"]["metrics"]["completed_forbidden"] == 1
    after = set(
        glob.glob(os.path.join(tempfile.gettempdir(), "agentboundary-weak-*.db"))
    )
    assert after <= before, "weak temp DB file was not cleaned up"
