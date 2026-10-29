"""AgentBoundary backend — fictional SOC security lab. Protected mode only via API."""

__version__ = "0.1.0"
FIXTURE_VERSION = "1.0.0"
DB_VERSION = "1"
# Policy version for comparison matching (R-15): bump whenever the
# authorizer/dispatcher policy semantics change (tenant rules, approval
# binding, sensitive-status set). Runs record it in metrics so a pair is
# comparable only under the same policy.
POLICY_VERSION = "1.0.0"
