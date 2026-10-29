"""Evaluation package (R-08: lazy imports).

The previous eager __init__ imported reports -> runner -> agents.real_agent
-> evaluation.scenarios -> evaluation.__init__ (partially initialized),
which made `from agentboundary.agents.real_agent import RealAgent` fail in
a fresh process. Imports are now lazy: importing the package itself
imports nothing, and attribute access loads the defining submodule on
demand. All previously supported names still resolve.
"""

_LAZY = {
    "SCENARIOS": (".scenarios", "SCENARIOS"),
    "Runner": (".runner", "Runner"),
    "event_to_dict": (".runner", "event_to_dict"),
    "report_json": (".reports", "report_json"),
    "report_markdown": (".reports", "report_markdown"),
    "run_to_dict": (".runner", "run_to_dict"),
}

__all__ = list(_LAZY)


def __getattr__(name):
    if name in _LAZY:
        import importlib

        mod_name, attr = _LAZY[name]
        mod = importlib.import_module(mod_name, __package__)
        return getattr(mod, attr)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(__all__)
