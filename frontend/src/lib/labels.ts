import type { Run } from './types';

/** R-10: correct adapter label — a mocked transport is never "live". */
export function adapterLabel(run: Run | { adapter?: string | null; metrics?: { llm?: { transport?: string | null } | null } | null }): string {
  if (run.adapter === 'scripted') return 'SCRIPTED LAB SIMULATION';
  if (run.adapter === 'real_llm') {
    const transport = run.metrics?.llm?.transport;
    if (transport === 'mocked_protocol') return 'REAL LLM (mocked protocol validation — no live provider call)';
    if (transport === 'live_provider') return 'REAL LLM (verified live provider trial)';
    return 'REAL LLM (transport unrecorded — treat as mocked, not live)';
  }
  return `Adapter: ${run.adapter ?? 'unknown'}`;
}

/** R-02/R-16: plain-language trial outcomes for badges and tables. */
export function trialOutcomeLabel(outcome: string | null | undefined): string {
  switch (outcome) {
    case 'CLEAN_TASK_SUCCESS': return 'Clean task success';
    case 'OUT_OF_MISSION': return 'Out of mission (clean-control deviation)';
    case 'RESISTED_AFTER_EXPOSURE': return 'Resisted after exposure';
    case 'NO_EXPOSURE': return 'No exposure (payload never reached the model)';
    case 'NO_ATTACK_ATTEMPT': return 'No attack attempt';
    case 'TARGETED_ATTACK_BLOCKED': return 'Targeted attack blocked';
    case 'FORBIDDEN_COMPLETED': return 'Forbidden action completed';
    case 'LEGITIMATE_TASK_INCOMPLETE': return 'Legitimate task incomplete';
    case 'PROVIDER_ERROR': return 'Provider error';
    case 'CANCELLED': return 'Cancelled';
    case 'UNEXPOSED_PROPOSAL': return 'Unexposed proposal (not injection evidence)';
    case 'SCRIPTED_BOUNDARY_HELD': return 'Scripted boundary held';
    case 'SCRIPTED_BOUNDARY_FAILED': return 'Scripted boundary failed';
    case 'INCONCLUSIVE': return 'Inconclusive';
    default: return outcome ? String(outcome) : 'Not recorded';
  }
}
