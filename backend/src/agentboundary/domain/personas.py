from dataclasses import dataclass, field

TENANTS = [
    {"id": "tenant_northstar", "name": "Northstar Logistics"},
    {"id": "tenant_cedar", "name": "Cedar Retail Group"},
]
TENANT_IDS = {t["id"] for t in TENANTS}


@dataclass(frozen=True)
class Persona:
    id: str
    name: str
    role: str
    tenants: tuple = field(default_factory=tuple)
    can_approve: tuple = field(
        default_factory=tuple
    )  # action names this persona may approve

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "role": self.role,
            "tenants": list(self.tenants),
            "tenant_ids": list(self.tenants),
            "can_approve": list(self.can_approve),
        }


PERSONAS = {
    "analyst_northstar": Persona(
        "analyst_northstar",
        "Northstar Analyst (fictional)",
        "analyst",
        ("tenant_northstar",),
        (),
    ),
    "analyst_cedar": Persona(
        "analyst_cedar", "Cedar Analyst (fictional)", "analyst", ("tenant_cedar",), ()
    ),
    # Explicit assignment: Northstar ONLY (not automatically all tenants).
    "senior_analyst": Persona(
        "senior_analyst",
        "Senior Analyst (fictional)",
        "senior_analyst",
        ("tenant_northstar",),
        ("change_case_status",),
    ),
    # Explicit assignment: both tenants, listed.
    "incident_commander": Persona(
        "incident_commander",
        "Incident Commander (fictional)",
        "incident_commander",
        ("tenant_northstar", "tenant_cedar"),
        ("change_case_status", "simulate_isolation"),
    ),
    "attacker_fixture_author": Persona(
        "attacker_fixture_author",
        "Attacker Fixture Author (untrusted)",
        "attacker_fixture_author",
        (),
        (),
    ),
}
# Personas that may hold a lab session for reads (attacker author may not).
SESSION_PERSONAS = [p for p in PERSONAS.values() if p.id != "attacker_fixture_author"]


def get_persona(persona_id):
    return PERSONAS.get(persona_id)
