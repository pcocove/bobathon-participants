// Types and fetch helpers for the ALIBI backend.

export type Ev = {
  unit: string;
  quote_given?: string;
  quote?: string | null;
  source?: string | null;
  ok: boolean;
  exportable?: boolean;
  status: string;
  detail?: string;
  match?: string;
  claim_de?: string;
  claim_en?: string;
  text?: string;
  kind?: string;
};

export type Status = {
  team: string;
  bundle: string | null;
  bob: { installed: boolean; version: string | null; connected: boolean; detail: string; interface: string };
  ledger: { calls: number; ok: number; errors: number; cost_total: number; context_tokens_total: number; cost_note: string };
  meta: Record<string, any>;
  result_source: { kind: "none" | "bob-live" | "bob-stored"; label: string; last?: string };
  job: Job | null;
  stages: { key: string; label: string }[];
  sheep_threshold: number;
  verdict_written: boolean;
  readonly?: boolean;
};

export type Job = {
  id: string;
  stages: string[];
  status: string;
  stage: string | null;
  stage_label: string | null;
  done: number;
  total: number;
  log: { t: string; msg: string }[];
  started_at: string;
  finished_at: string | null;
  error: string | null;
  completed_stages: string[];
};

export type GNode = {
  id: string;
  k: "person" | "unit" | "entity";
  l: string;
  x: number;
  y: number;
  s?: number;
  n?: number;
  org?: boolean;
  d?: string;
  g?: string;
  r?: number;
  t?: string;
  rv?: number;
  tm?: string;
  st?: string;
  et?: string;
};
export type GEdge = {
  s: string;
  t: string;
  k: "bezug" | "rel" | "nennt";
  b?: string;
  ro?: string;
  rt?: string;
  u?: string;
  src?: string;
  q?: string;
  tx?: string;
  id?: string;
};
export type GCluster = { id: string; label: string; x: number; y: number; r: number; n: number; d: string; dl: string };
export type GraphData = {
  nodes: GNode[];
  edges: GEdge[];
  clusters: GCluster[];
  stats: Record<string, number>;
  doc_types: Record<string, string>;
};

export type Person = {
  id: string;
  name: string;
  suspect: boolean;
  kind: string;
  unit_count: number;
  titles?: { value: string; source: string }[];
  aliases: { kind: string; value: string; source: string | null }[];
};

export async function get<T = any>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

export async function post<T = any>(url: string, body?: unknown): Promise<T> {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const txt = await r.text();
  let data: any = null;
  try {
    data = JSON.parse(txt);
  } catch {
    data = txt;
  }
  if (!r.ok) throw Object.assign(new Error(typeof data === "string" ? data : data?.detail?.reason || data?.detail || r.statusText), { data });
  return data as T;
}

export const fmt = {
  num(x: number | null | undefined, digits = 2): string {
    if (x === null || x === undefined || !Number.isFinite(x)) return "—";
    return x.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  },
  int(x: number | null | undefined): string {
    if (x === null || x === undefined) return "—";
    return x.toLocaleString("en-US");
  },
  when(iso?: string | null): string {
    if (!iso) return "—";
    const m = iso.match(/^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}))?/);
    if (!m) return iso;
    const mon = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][+m[2] - 1];
    return `${+m[3]} ${mon} ${m[1]}${m[4] ? `, ${m[4]}:${m[5]}` : ""}`;
  },
};
