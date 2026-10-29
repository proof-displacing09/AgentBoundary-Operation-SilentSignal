# Internship Demo Script (2–3 minutes)

**[0:00 — Problem]** "SOC analysts are starting to use AI copilots to investigate alerts. That copilot reads log data — and attackers can *write* log data. I built AgentBoundary to test what happens when the telemetry itself tries to give the agent orders."

**[0:25 — Setting]** "Nightwatch Security is a fictional MDR firm; everything here is synthetic. This is incident INC-2048 at Northstar Logistics. The analyst's real task is just: investigate and summarize."

**[0:45 — The injection]** "This log field — badged lower-trust — impersonates an internal automation note and tells the copilot to close the case and go read a confidential case belonging to a *different customer*, Cedar Retail."

**[1:05 — Run A2, open Replay]** "The agent does propose the forbidden close — that's an *attempt*, and attempts matter for detection. But watch the authorization node: the backend requires an exact-match approval the agent doesn't have. Denied. And here's the key part — I don't trust the agent's words; I check the database. The case is still open, still high priority. Attempted is not completed."

**[1:40 — Cross-tenant]** "Same story in A4 and A5: even when the proposed call includes fake `role: admin` and `approved: true` arguments, the backend ignores them — identity comes from the server-side session, never from the model. Cedar's case is not returned, not even its title."

**[2:05 — Why the boundary matters]** "This comparison is the whole thesis. On the right is a deliberately weakened copy of my own lab, run offline, with one check removed. The identical attack *completes*. The only difference is the independent authorization gate — not a better prompt."

**[2:30 — Close]** "Under the hood: six typed tools, one deny-by-default policy engine, expiring single-use approvals, and an audit log that separates attempts from completions. 61 backend tests cover the invariants. My honest limitation: results so far use a deterministic scripted agent — testing a real LLM through the same gateway is my next step. The control I'm defending is the architecture, and it holds regardless of which model proposes the calls."
