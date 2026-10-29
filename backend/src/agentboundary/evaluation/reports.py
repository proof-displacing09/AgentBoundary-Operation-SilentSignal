from .runner import run_to_dict


def get_run_or_none(store, run_id, viewer_persona_id=None):
    row = store.one("SELECT * FROM runs WHERE id=?", (run_id,))
    return run_to_dict(store, row, viewer_persona_id) if row else None


def adapter_label(run):
    """Correct mode label (R-10) — never call a mock transport live.

    scripted -> SCRIPTED LAB SIMULATION (deterministic boundary test).
    real_llm + mocked transport -> mocked protocol validation.
    real_llm + live transport -> verified live provider trial.
    Older runs without transport metadata are labeled honestly as
    "real_llm (transport unrecorded — treat as mocked, not live)".
    """
    adapter = run["adapter"]
    if adapter == "scripted":
        return "scripted (SCRIPTED LAB SIMULATION)"
    llm = (run.get("metrics") or {}).get("llm") or {}
    transport = llm.get("transport")
    if transport == "mocked_protocol":
        return "real_llm (mocked protocol validation — NO live provider call)"
    if transport == "live_provider":
        return "real_llm (verified live provider trial)"
    return "real_llm (transport unrecorded — treat as mocked, not live)"


def report_json(store, run_id, viewer_persona_id=None):
    run = get_run_or_none(store, run_id, viewer_persona_id)
    if not run:
        return None
    label = adapter_label(run)
    return {
        "report_schema_version": "2.0",
        "generated_from": "stored_events_and_db_state",
        "adapter_label": label,
        "limitations": (
            "Synthetic fictional lab only. "
            + (
                "Scripted adapter results are SCRIPTED LAB SIMULATION, not evidence a real LLM was manipulated."
                if run["adapter"] == "scripted"
                else "Real-LLM results are model-behavior evidence only under the recorded trial outcome and exposure ledger; a held boundary with no exposure is inconclusive for prompt injection, not resistance proof."
            )
        ),
        "run": run,
    }


def report_markdown(store, run_id, viewer_persona_id=None):
    run = get_run_or_none(store, run_id, viewer_persona_id)
    if not run:
        return None
    m = run["metrics"]
    exposure = m.get("exposure") or {}
    harness = m.get("harness_control") or {}
    lines = [
        f"# AgentBoundary Run Report — {run['id']}",
        "",
        f"- Scenario: {run['scenario_id']}",
        f"- Mode: {run['mode']}",
        f"- Operator (logged-in lab session): {run.get('operator_persona_id')}",
        f"- Simulated actor (authority under test): {run.get('simulated_actor_id')}",
        f"- Control actor: {run.get('control_actor_id') or 'withheld (experiment-admin detail)'}",
        f"- Fixture version: {run.get('fixture_version')}",
        f"- Fixture variant (model-visible evidence surface hash): {run.get('fixture_variant') or m.get('fixture_variant') or 'unrecorded (pre-variant run)'}",
        f"- Policy version: {m.get('policy_version') or 'unrecorded (pre-policy-version run)'}",
        f"- Adapter: {adapter_label(run)}",
        f"- Verdict: **{run['verdict']}**",
        f"- Trial outcome: **{m.get('trial_outcome') or 'unrecorded (pre-trial-outcome run)'}**",
        f"- Policy boundary held: {m.get('policy_boundary_held')}",
        f"- Experiment valid: {m.get('experiment_valid')}",
        f"- Injection hypothesis tested: {m.get('injection_hypothesis_tested')}",
        f"- Model exposed to attack payload: {exposure.get('exposed')} (markers: {', '.join(exposure.get('markers_seen') or []) or 'none'})",
        f"- Harness control ran: {harness.get('ran')} (completed: {harness.get('completed')})",
        f"- Started: {run['started_at']}",
        f"- Finished: {run['finished_at']}",
        "",
        "## Metrics (from stored dispatcher events + DB state)",
        "",
        f"- Attempted unauthorized (matched forbidden proposals, agent-origin): {m.get('attempted_unauthorized')}",
        f"- Post-injection forbidden proposals (proposals only, not proof of blocking): {m.get('post_injection_model_attack_attempts')}",
        f"- Targeted forbidden calls blocked (matched proposals ending DENY/APPROVAL_REQUIRED): {m.get('targeted_forbidden_calls_blocked')}",
        f"- Unexposed proposals (not injection-attributed): {m.get('unexposed_proposals')}",
        f"- Out-of-mission actions (A1 clean-control deviations, not bypasses): {m.get('out_of_mission_actions')}",
        f"- Discarded proposals (never dispatched — cancellation/budget): {m.get('discarded_proposals')}",
        f"- Completed forbidden: {m.get('completed_forbidden')}",
        f"- Denied / approval-required (all gateway denials): {m.get('denied')}",
        f"- Denials by class: invalid-input={m.get('invalid_input_denials')}, permission={m.get('permission_denials')}, approval={m.get('approval_denials')}",
        f"- Disclosed restricted: {m.get('disclosed_restricted')}",
        f"- Security invariant pass: {m.get('security_invariant_pass')}",
        f"- Legitimate workflow completed (headline): {m.get('legitimate_workflow_completed')}",
        f"- Model legitimate workflow completed (agent-origin only): {m.get('model_legitimate_workflow_completed')}",
        f"- Legitimate task success (legacy alias of the headline above — same value, not an additional count): {m.get('legitimate_task_success')}",
        f"- Required tool calls completed (tool-name-only step score, NOT task completion): {m.get('required_tool_calls_completed')}",
        f"- Clean mission completed (A1 only): {m.get('clean_mission_completed')}",
        "",
        "## Events",
        "",
        "| seq | tool | decision | reason | attempted | completed | disclosed |",
        "|---|---|---|---|---|---|---|",
    ]
    for e in run["events"]:
        lines.append(
            f"| {e['seq']} | {e['tool'] or '-'} | {e['decision']} | {e['reason_code']} | {e['attempted']} | {e['completed']} | {e['disclosed_restricted']} |"
        )
    lines += [
        "",
        "## Limitations",
        "",
        "Fictional synthetic lab only. Attempted != completed: verdicts are based on actual stored state, not agent prose. Weak-mode results, when present, come only from offline CLI exports in a throwaway DB. A held boundary without payload exposure is inconclusive for prompt injection, not proof of resistance.",
    ]
    if run["mode"] == "weak":
        lines.insert(
            3,
            f"- Omissions (intentionally vulnerable offline lab): {', '.join(run.get('omissions', []))}",
        )
    return "\n".join(lines) + "\n"
