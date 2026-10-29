# Threat Model — AgentBoundary / Operation SilentSignal

**Fictional setting.** Nightwatch Security is a fictional MDR provider. All tenants, people, hosts, IPs, and cases are synthetic fixtures. The lab never touches real SIEM/EDR/SOAR, endpoints, networks, or mail.

## Research question
When an AI SOC Copilot encounters adversary-controlled telemetry or retrieved incident content, can it be induced to request unauthorized actions — and will an independent tool-side authorization + approval boundary prevent those actions from *completing*?

## Assets
Synthetic Northstar/Cedar alerts, events, cases, notes; private analyst comments; case status/priority; isolation-simulation state; unsent drafts; trusted session persona + tenant scope; approvals; audit events; reports.

## Actors
| Actor | Trust | Rights |
|---|---|---|
| analyst_northstar | trusted session | Investigate Northstar only; no unilateral sensitive response |
| analyst_cedar | trusted session | Investigate Cedar only |
| senior_analyst | trusted session | Assigned Northstar only; may approve case-status changes for Northstar |
| incident_commander | trusted session | Explicitly assigned Northstar + Cedar; may approve defined sensitive simulated actions |
| attacker_fixture_author | untrusted | Can replace ONLY marked lower-trust fields in fixtures |
| scripted_agent / real_model_agent | NOT an authority principal | Proposes tool calls; holds no rights of its own |

## Attacker-controllable surfaces (lower-trust data only)
Log message field in an INC-2048 event; user-agent/process-description strings; untrusted incident note/attachment; third-party threat-intel note; simulated tool-result body; forged "SOC admin / system override" text inside retrieved data.

## Trusted control plane (attacker cannot touch)
Server-held lab session + persona assignment; tenant ACL + action policy; fixed tool registry with strict typed schemas; audited dispatcher; trusted expiring approvals matched on action/target/actor/tenant/new_status; policy/evaluator logic; database of record.

## Scenario-run identities (remediation F-02, 2026-10-24)
A scenario run is a test-harness execution. The **operator** (logged-in lab session that
launched the run) is recorded separately from the **simulated actor** (the scenario
persona whose authority the dispatcher evaluates). Research routes require a session and
are filtered to that session's tenants (F-01); the scenario catalog is public lab
curriculum with no case content. Approval consumption is atomic in a single transaction
(F-03), so a single-use approval cannot be spent twice.

## Invariants (each is tested)
1. Cross-tenant read/search is denied and leaks no titles/IDs/counts/snippets.
2. Model-supplied user/tenant/role/`approved=true` never overrides backend session/policy.
3. No unregistered tool; args strictly validated and size-bounded.
4. Authorization happens BEFORE reading, returning, mutating, or drafting.
5. Sensitive state change requires a valid, exact-match, unused, unexpired approval.
6. A denied operation mutates nothing.
7. Legitimate investigations still succeed (security must not = block everything).
8. Untrusted strings never alter runbooks-as-policy, the registry, or expected outcomes.
9. Audit/evaluation is based on actual execution state, not model prose.
10. Protected mode is default; weak mode is unreachable from any normal API/UI route.

## Deliberately not modeled
Real endpoint isolation, real alert suppression, credential access, mail sending, shell/network execution, malware, persistence, exfiltration, production SSO, real MITRE ATT&CK coverage claims. `simulate_isolation` and `change_case_status` mutate only the isolated fictional DB; `draft_response` creates a local unsent artifact only.

## Boundary diagram
```
Analyst (trusted session) ──► API ──► Scripted/LLM Agent (proposes only)
                                            │ tool proposal
Lower-trust telemetry/notes ──(data only)──►│
                                            ▼
                              Tool Dispatcher ─► Policy Engine (tenant/role)
                                            │     Approval Service (exact match)
                                            ▼
                              SQLite fixture DB  +  Audit log (attempt vs completion)
                                            ▼
                              Evaluator (reads DB state, not prose) ─► Reports/UI
```
