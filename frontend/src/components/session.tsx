import { createContext, useContext } from 'react';
import type { Persona } from '../lib/types';

export interface SessionCtx {
  persona: Persona | null;
  personas: Persona[];
  switchPersona: (id: string) => Promise<void>;
  push: (text: string, error?: boolean) => void;
  navigate: (route: string) => void;
  sessionVersion: number;
}
export const SessionContext = createContext<SessionCtx>({
  persona: null, personas: [], switchPersona: async () => {}, push: () => {}, navigate: () => {}, sessionVersion: 0,
});
export const useSession = () => useContext(SessionContext);
