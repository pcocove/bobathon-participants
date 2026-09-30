// Small global state without extra libraries: network selection, source viewer, presentation mode.
import { useSyncExternalStore } from "react";

export type Focus = {
  title: string;
  nodes: string[]; // node IDs (p:…, u:…, e:…)
  order?: string[]; // order of an evidence chain
  kind?: "person" | "chain" | "prevention" | "unit" | "search";
};

type State = {
  selected: string | null; // node or edge
  focus: Focus | null;
  source: { ref?: string; unit?: string } | null;
  present: boolean;
  analysisVersion: number;
};

let state: State = { selected: null, focus: null, source: null, present: false, analysisVersion: 0 };
const subs = new Set<() => void>();

export function setState(p: Partial<State>) {
  state = { ...state, ...p };
  subs.forEach((f) => f());
}

export function getState() {
  return state;
}

export function useStore<T>(sel: (s: State) => T): T {
  return useSyncExternalStore(
    (f) => {
      subs.add(f);
      return () => subs.delete(f);
    },
    () => sel(state),
  );
}

export function showInGraph(focus: Focus, select?: string) {
  setState({ focus, selected: select ?? null });
  document.getElementById("netz")?.scrollIntoView({ behavior: "smooth", block: "start" });
}

export function openSource(ref?: string | null, unit?: string | null) {
  if (!ref && !unit) return;
  setState({ source: { ref: ref ?? undefined, unit: unit ?? undefined } });
}
