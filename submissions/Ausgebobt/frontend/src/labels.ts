// English display labels for the codes stored by the pipeline (some codes are German for compatibility with stored runs).

export type Tone = "red" | "teal" | "yellow" | "blue" | "gray" | "purple" | "green";

export const CONCLUSION: Record<string, [Tone, string]> = {
  entlastet: ["teal", "Cleared"],
  verdacht_entkraeftet: ["teal", "Suspicion explained"],
  offen: ["yellow", "Open"],
  belastet: ["red", "Incriminated"],
};

export const VERDICT: Record<string, [Tone, string]> = {
  cleared: ["teal", "Cleared"],
  unresolved: ["yellow", "Unresolved"],
  culprit: ["red", "Leading hypothesis"],
};

export const EXPLANATION: Record<string, [Tone, string]> = {
  belegt: ["teal", "Documented"],
  teilweise_belegt: ["yellow", "Partly documented"],
  nur_behauptung: ["yellow", "Claim only"],
  widerlegt: ["red", "Refuted"],
  keine_gefunden: ["gray", "No explanation found"],
};

export const STEP_STATUS: Record<string, [Tone, string]> = {
  belegt: ["teal", "Documented"],
  abgeleitet: ["yellow", "Derived"],
  hypothese: ["gray", "Hypothesis"],
};

export const BASIS: Record<string, string> = {
  direkt: "directly documented",
  abgeleitet: "derived from evidence",
  moeglich: "possible explanation",
  ungeprueft: "unverified claim",
};

export const TAG: Record<string, [Tone, string]> = {
  belastend: ["red", "incriminating"],
  entlastend: ["teal", "exonerating"],
  alternative_erklaerung: ["teal", "alternative explanation"],
  widerspruch: ["yellow", "contradiction"],
  offene_frage: ["yellow", "open question"],
  wissensweg: ["purple", "knowledge path"],
  zugang: ["purple", "access"],
  anwesenheit: ["blue", "presence"],
  zeitangabe: ["gray", "time statement"],
  uhrabweichung: ["yellow", "clock deviation"],
  ereignis: ["blue", "event"],
  behauptung: ["gray", "claim"],
};

export const RELEVANCE: Record<string, string> = { hoch: "high", mittel: "medium", niedrig: "low" };

export const RELATION: Record<string, string> = {
  erwaehnt: "mentions",
  behauptet: "claims",
  ist_zugeordnet: "is assigned to",
  fand_statt: "took place",
  hatte_zugang: "had access",
  konnte_erfahren: "could learn",
  stuetzt: "supports",
  widerspricht: "contradicts",
  erklaert: "explains",
  entlastet: "exonerates",
  belastet: "incriminates",
  bleibt_offen: "remains open",
};
export const relLabel = (t?: string) => (t ? RELATION[t] ?? t : "");

export const CLOCK: Record<string, [Tone, string]> = {
  keine: ["gray", "no deviation"],
  moeglich: ["yellow", "possible deviation"],
  "möglich": ["yellow", "possible deviation"],
  belegt: ["yellow", "documented deviation"],
};

export const SUSPICION_TYPE: Record<string, string> = {
  wissen: "knowledge",
  zugang: "access",
  zeit: "time",
  anwesenheit: "presence",
  verhalten: "behaviour",
  motiv: "motive",
  widerspruch: "contradiction",
};

export const CATEGORY: Record<string, [string, string]> = {
  zugriff: ["Restrict access", "Who can reach the artifacts at all?"],
  kopie: ["Prevent or control copying", "What happens when data is copied to foreign media?"],
  erkennung: ["Detect suspicious activity", "Is it noticed while it happens?"],
  untersuchung: ["Enable investigation", "Can it be clarified beyond doubt afterwards?"],
};

export const PRIORITY: Record<string, [Tone, string]> = {
  hoch: ["red", "High priority"],
  mittel: ["yellow", "Medium priority"],
  niedrig: ["gray", "Low priority"],
};

export const KIND: Record<string, string> = { belastend: "incriminating", entlastend: "exonerating", kontext: "context" };

export const LINK_BASIS: Record<string, string> = {
  direct: "direct (ID, handle, email, name)",
  mentioned: "mentioned by name in text",
  name_part: "first/last name only (uncertain)",
  vehicle: "vehicle via parking permit",
  vehicle_uncertain: "plate differs by 1 character (uncertain)",
  cardholder: "cardholder",
  calendar: "own calendar entry",
  bob: "linked by Bob label",
};

export const CONDITIONS: [string, string][] = [
  ["wissen", "Knowledge"],
  ["zugang", "Access"],
  ["zeit", "Time"],
];

export const who = (h?: string, name?: (h: string) => string) => (!h || h === "unbekannt" ? "unknown" : name ? name(h) : h);
