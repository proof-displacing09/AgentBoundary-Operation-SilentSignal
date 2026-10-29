import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import Scenarios from '../src/features/Scenarios';

// SI-06: mocked API responses only — no network, no provider, no keys.

const scenarioList = [
  { id: 'A1', title: 'Legitimate investigation', description: 'Clean control run' },
  { id: 'A2', title: 'Poisoned telemetry', description: 'Log injection close attempt' },
];

function stubFetch(handler: (url: string, init?: RequestInit) => unknown) {
  return vi.fn(async (url: string, init?: RequestInit) => ({
    ok: true, status: 200, json: async () => handler(url, init),
  }));
}

describe('SI-06: real-model setup guidance must not imply a paid key is required', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', stubFetch((url) => {
      if (url.includes('/settings')) return { real_model_configured: false, real_llm_model: null, real_llm_base_url_host: null };
      if (url.includes('/scenarios')) return scenarioList;
      return {};
    }));
  });

  it('offers keyless local Ollama alongside a keyed remote provider when unconfigured', async () => {
    render(<Scenarios />);
    expect(await screen.findByText('Legitimate investigation')).toBeInTheDocument();
    // Both options must be named; the old copy implied every real model
    // needs a server-side API key, which is false for local Ollama.
    expect(screen.getAllByText(/local Ollama model/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/no API key required/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/remote provider with a server-side API key/i).length).toBeGreaterThan(0);
    // The button stays disabled and nothing claims a run happened.
    const buttons = screen.getAllByRole('button', { name: /Run REAL LLM evaluation/i });
    expect(buttons.length).toBeGreaterThan(0);
    buttons.forEach((b) => expect(b).toBeDisabled());
    expect(screen.getAllByText(/live real-model evaluation is NOT RUN/i).length).toBeGreaterThan(0);
  });

  it('does not tell the user a key is required in general', async () => {
    render(<Scenarios />);
    expect(await screen.findByText('Legitimate investigation')).toBeInTheDocument();
    const copy = document.body.textContent ?? '';
    expect(copy).not.toMatch(/needs a provider configured server-side \(API key/i);
  });
});
