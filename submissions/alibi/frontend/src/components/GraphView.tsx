import Graph from "graphology";
import Sigma from "sigma";
import { useEffect, useMemo, useRef, useState } from "react";
import { get, type GraphData, type Person } from "../api";
import { getState, setState, showInGraph, useStore } from "../store";
import { DetailPanel } from "./DetailPanel";
import { relLabel } from "../labels";

// Carbon g100 data-visualisation colours
export const C = {
  suspect: "#f4f4f4",
  person: "#8d8d8d",
  org: "#6f6f6f",
  belastend: "#fa4d56",
  entlastend: "#08bdba",
  offen: "#f1c21b",
  neutral: "#4589ff",
  reviewed: "#525252",
  none: "#333333",
  entity: "#a56eff",
  dim: "#262626",
};
const REL_COLOR: Record<string, string> = {
  belastet: "#fa4d56",
  entlastet: "#08bdba",
  erklaert: "#3ddbd9",
  widerspricht: "#f1c21b",
  bleibt_offen: "#f1c21b",
  konnte_erfahren: "#a56eff",
  hatte_zugang: "#a56eff",
  stuetzt: "#78a9ff",
};
const DOC_COLOR: Record<string, string> = {
  interview: "#ff7eb6", notebook: "#ee5396", pdf: "#be95ff", scan: "#be95ff", photo: "#be95ff", email: "#33b1ff", jira: "#78a9ff",
  helpdesk: "#3ddbd9", meeting: "#6fdc8c", diligence: "#fa4d56", expense: "#d2a106", slack: "#a56eff", calendar: "#08bdba",
  card: "#ff832b", garage: "#a8a8a8", permit: "#a8a8a8", meta: "#6f6f6f",
};

type Props = { persons: Person[]; analysis: any; preview: boolean };

export function GraphView({ persons, analysis, preview }: Props) {
  const [data, setData] = useState<GraphData | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const holder = useRef<HTMLDivElement>(null);
  const overlay = useRef<HTMLCanvasElement>(null);
  const sigmaRef = useRef<Sigma | null>(null);
  const graphRef = useRef<Graph | null>(null);
  const st = useRef({
    docOff: new Set<string>(),
    relOff: new Set<string>(),
    showBezug: true,
    showEntities: true,
    focus: null as Set<string> | null,
    order: [] as string[],
    selected: null as string | null,
    hovered: null as string | null,
  });
  const [, force] = useState(0);
  const rerender = () => force((x) => x + 1);
  const focus = useStore((s) => s.focus);
  const selected = useStore((s) => s.selected);
  const version = useStore((s) => s.analysisVersion);
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<{ persons: any[]; units: any[] } | null>(null);

  useEffect(() => {
    setData(null);
    get<GraphData>("api/graph").then(setData, (e) => setErr(String(e.message)));
  }, [version]);

  // ------------------------------------------------------------ build graph + sigma (once per data version)
  useEffect(() => {
    if (!data || !holder.current) return;
    const g = new Graph({ multi: true, type: "undirected", allowSelfLoops: false });
    for (const n of data.nodes) {
      let color = C.none;
      let size = 1.6;
      if (n.k === "person") {
        color = n.s ? C.suspect : n.org ? C.org : C.person;
        size = n.s ? 13 : 6.5;
      } else if (n.k === "unit") {
        color = n.t === "none" ? (n.rv ? C.reviewed : C.none) : (C as any)[n.t ?? "neutral"] ?? C.neutral;
        size = [1.7, 2.3, 3.3, 4.8][n.r ?? 0];
      } else {
        color = C.entity;
        size = Math.min(7, 2.6 + Math.sqrt(n.n ?? 1));
      }
      g.addNode(n.id, { x: n.x, y: -n.y, size, color, label: n.l, kind: n.k, d: n.d, g: n.g, s: n.s, t: n.t, r: n.r });
    }
    for (const e of data.edges) {
      if (!g.hasNode(e.s) || !g.hasNode(e.t)) continue;
      const color = e.k === "rel" ? REL_COLOR[e.rt ?? ""] ?? "#8d8d8d" : e.k === "bezug" ? (e.b === "name_part" || e.b === "vehicle_uncertain" ? "#525252" : "#8d8d8d") : "#6929c4";
      const attrs = { size: e.k === "rel" ? 1.1 : 0.5, color, kind: e.k, rt: e.rt, b: e.b, s0: e.s, t0: e.t, u: e.u, q: e.q, tx: e.tx, src: e.src, ro: e.ro };
      if (e.id && !g.hasEdge(e.id)) g.addEdgeWithKey(e.id, e.s, e.t, attrs);
      else g.addEdge(e.s, e.t, attrs);
    }
    graphRef.current = g;
    const S = st.current;
    const renderer = new Sigma(g, holder.current, {
      renderEdgeLabels: false,
      enableEdgeEvents: true,
      labelRenderedSizeThreshold: 5.5,
      labelFont: "IBM Plex Sans",
      labelSize: 13,
      labelWeight: "500",
      labelColor: { color: "#f4f4f4" },
      labelDensity: 0.9,
      labelGridCellSize: 90,
      zIndex: true,
      minCameraRatio: 0.015,
      maxCameraRatio: 2.2,
      defaultEdgeColor: "#525252",
      stagePadding: 24,
      hideEdgesOnMove: data.edges.length > 6000,
      nodeReducer: (node, attr) => {
        const res: any = { ...attr };
        if (attr.kind === "unit" && S.docOff.has(attr.d)) return { ...res, hidden: true };
        if (attr.kind === "entity" && !S.showEntities) return { ...res, hidden: true };
        if (S.focus) {
          if (S.focus.has(node)) {
            res.zIndex = 2;
            if (attr.kind === "person" || S.focus.size <= 80 || attr.r >= 3) res.forceLabel = true;
            if (attr.kind === "unit") res.size = Math.max(attr.size * 1.6, 3.2);
          } else {
            res.color = C.dim;
            res.label = "";
            res.zIndex = 0;
          }
        } else if (attr.kind === "person" && attr.s) res.forceLabel = true;
        if (node === S.selected || node === S.hovered) {
          res.highlighted = true;
          res.forceLabel = true;
          res.zIndex = 3;
        }
        return res;
      },
      edgeReducer: (edge, attr) => {
        const res: any = { ...attr };
        const f = S.focus;
        const sd = g.getNodeAttributes(attr.s0);
        const td = g.getNodeAttributes(attr.t0);
        if ((sd.kind === "unit" && S.docOff.has(sd.d)) || (td.kind === "unit" && S.docOff.has(td.d))) return { ...res, hidden: true };
        if ((sd.kind === "entity" || td.kind === "entity") && !S.showEntities) return { ...res, hidden: true };
        if (attr.kind === "rel") {
          // overview without lines; relations only appear for a selection (no decorative lines)
          if (S.relOff.has(attr.rt) || !f || !(f.has(attr.s0) && f.has(attr.t0))) return { ...res, hidden: true };
          res.size = 2;
          return res;
        }
        if (attr.kind === "bezug") {
          if (!(f && S.showBezug && f.has(attr.s0) && f.has(attr.t0))) return { ...res, hidden: true };
          if (f.size > 150) res.color = "#6f6f6f55";
          else if (f.size > 40) res.color = "#8d8d8daa";
          return res;
        }
        // nennt
        if (!(f && f.has(attr.s0) && f.has(attr.t0) && S.showEntities)) return { ...res, hidden: true };
        return res;
      },
    });
    sigmaRef.current = renderer;

    const neighborsFocus = (node: string) => {
      const set = new Set<string>([node]);
      g.forEachNeighbor(node, (nb) => set.add(nb));
      return set;
    };
    renderer.on("clickNode", ({ node }) => {
      const a = g.getNodeAttributes(node);
      const nodes = [...neighborsFocus(node)];
      setState({ selected: node, focus: { title: a.label, nodes, kind: a.kind === "person" ? "person" : "unit" } });
    });
    renderer.on("clickEdge", ({ edge }) => {
      const a = g.getEdgeAttributes(edge);
      if (a.kind !== "rel") return;
      setState({ selected: `edge:${edge}`, focus: { title: `${relLabel(a.rt)}: ${g.getNodeAttribute(a.s0, "label")} – ${g.getNodeAttribute(a.t0, "label")}`, nodes: [a.s0, a.t0, a.u ? `u:${a.u}` : a.s0], kind: "unit" } });
    });
    renderer.on("clickStage", () => setState({ selected: null, focus: null }));
    renderer.on("enterNode", ({ node }) => {
      S.hovered = node;
      renderer.refresh({ skipIndexation: true });
    });
    renderer.on("leaveNode", () => {
      S.hovered = null;
      renderer.refresh({ skipIndexation: true });
    });
    renderer.on("afterRender", () => drawOverlay());
    const ro = new ResizeObserver(() => drawOverlay());
    ro.observe(holder.current);
    applyFocus();
    return () => {
      ro.disconnect();
      renderer.kill();
      sigmaRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  // ------------------------------------------------------------ overlay: file groups, evidence chains
  function drawOverlay() {
    const r = sigmaRef.current;
    const cv = overlay.current;
    const g = graphRef.current;
    if (!r || !cv || !data || !g) return;
    const dpr = window.devicePixelRatio || 1;
    const w = cv.clientWidth;
    const h = cv.clientHeight;
    if (cv.width !== w * dpr || cv.height !== h * dpr) {
      cv.width = w * dpr;
      cv.height = h * dpr;
    }
    const ctx = cv.getContext("2d")!;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    const S = st.current;
    for (const cl of data.clusters) {
      const c0 = r.graphToViewport({ x: cl.x, y: -cl.y });
      const c1 = r.graphToViewport({ x: cl.x + cl.r, y: -cl.y });
      const rad = Math.hypot(c1.x - c0.x, c1.y - c0.y);
      if (c0.x + rad < 0 || c0.x - rad > w || c0.y + rad < 0 || c0.y - rad > h) continue;
      const off = S.docOff.has(cl.d);
      ctx.beginPath();
      ctx.arc(c0.x, c0.y, rad, 0, Math.PI * 2);
      ctx.fillStyle = off ? "rgba(255,255,255,0.005)" : "rgba(255,255,255,0.025)";
      ctx.fill();
      ctx.strokeStyle = off ? "rgba(255,255,255,0.04)" : (DOC_COLOR[cl.d] ?? "#6f6f6f") + "55";
      ctx.lineWidth = 1;
      ctx.stroke();
      if (rad > 22 && !off) {
        const fs = Math.max(10.5, Math.min(15, rad / 7));
        ctx.font = `600 ${fs}px "IBM Plex Sans", sans-serif`;
        ctx.fillStyle = (DOC_COLOR[cl.d] ?? "#a8a8a8") + (S.focus ? "88" : "ee");
        ctx.textAlign = "center";
        ctx.fillText(`${cl.label} · ${cl.n.toLocaleString("en-US")}`, c0.x, c0.y - rad - 6);
      }
    }
    // Beweiskette: nummerierte Schritte, gestrichelt verbunden
    if (S.order.length) {
      const pts = S.order.filter((n) => g.hasNode(n)).map((n) => {
        const a = g.getNodeAttributes(n);
        return r.graphToViewport({ x: a.x, y: a.y });
      });
      ctx.setLineDash([6, 5]);
      ctx.strokeStyle = "rgba(241,194,27,0.95)";
      ctx.lineWidth = 2;
      ctx.beginPath();
      pts.forEach((p, i) => (i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y)));
      ctx.stroke();
      ctx.setLineDash([]);
      pts.forEach((p, i) => {
        ctx.beginPath();
        ctx.arc(p.x + 12, p.y - 12, 10, 0, Math.PI * 2);
        ctx.fillStyle = "#f1c21b";
        ctx.fill();
        ctx.fillStyle = "#161616";
        ctx.font = "700 11px 'IBM Plex Mono', monospace";
        ctx.textAlign = "center";
        ctx.fillText(String(i + 1), p.x + 12, p.y - 8);
      });
    }
  }

  // ------------------------------------------------------------ focus from global state
  function applyFocus() {
    const r = sigmaRef.current;
    const g = graphRef.current;
    if (!r || !g) return;
    const S = st.current;
    const f = getFocus();
    S.selected = getSelected();
    if (f && f.nodes.length) {
      const set = new Set(f.nodes.filter((n) => g.hasNode(n)));
      // chain: keep only nodes that exist in the graph
      S.focus = set.size ? set : null;
      S.order = f.kind === "chain" ? (f.order ?? f.nodes).filter((n) => g.hasNode(n)) : [];
      if (set.size) fitTo([...set]);
    } else {
      S.focus = null;
      S.order = [];
    }
    r.refresh({ skipIndexation: true });
    rerender();
  }
  const getFocus = () => getState().focus;
  const getSelected = () => getState().selected;

  useEffect(() => {
    applyFocus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focus, selected]);

  function fitTo(nodes: string[]) {
    const r = sigmaRef.current;
    if (!r) return;
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const n of nodes) {
      const d = r.getNodeDisplayData(n);
      if (!d) continue;
      x0 = Math.min(x0, d.x); y0 = Math.min(y0, d.y); x1 = Math.max(x1, d.x); y1 = Math.max(y1, d.y);
    }
    if (!Number.isFinite(x0)) return;
    const ratio = Math.min(1.1, Math.max(0.04, Math.max(x1 - x0, y1 - y0) * 1.35 + 0.02));
    r.getCamera().animate({ x: (x0 + x1) / 2, y: (y0 + y1) / 2, ratio }, { duration: 650 });
  }

  // ------------------------------------------------------------ filters
  const docCounts = useMemo(() => {
    const m = new Map<string, number>();
    data?.nodes.forEach((n) => n.k === "unit" && m.set(n.d!, (m.get(n.d!) ?? 0) + 1));
    return [...m.entries()].sort((a, b) => b[1] - a[1]);
  }, [data]);
  const relCounts = useMemo(() => {
    const m = new Map<string, number>();
    data?.edges.forEach((e) => e.k === "rel" && m.set(e.rt!, (m.get(e.rt!) ?? 0) + 1));
    return [...m.entries()].sort((a, b) => b[1] - a[1]);
  }, [data]);
  const toggle = (set: Set<string>, k: string) => {
    set.has(k) ? set.delete(k) : set.add(k);
    sigmaRef.current?.refresh({ skipIndexation: true });
    rerender();
  };

  // ------------------------------------------------------------ search
  useEffect(() => {
    if (!q.trim()) {
      setHits(null);
      return;
    }
    const t = setTimeout(() => get(`api/search?q=${encodeURIComponent(q)}&limit=25`).then(setHits, () => setHits(null)), 250);
    return () => clearTimeout(t);
  }, [q]);

  const sortedPersons = useMemo(() => [...persons].sort((a, b) => a.name.localeCompare(b.name, "de")), [persons]);
  const pstatus = (id: string) => analysis?.final?.persons?.find((p: any) => p.id === id)?.verdict;

  const selectPerson = (id: string) => {
    const g = graphRef.current;
    const node = `p:${id}`;
    if (!g || !g.hasNode(node)) return;
    const nodes = [node, ...g.neighbors(node)];
    setState({ selected: node, focus: { title: g.getNodeAttribute(node, "label"), nodes, kind: "person" } });
  };

  const zoom = (f: number) => {
    const cam = sigmaRef.current?.getCamera();
    if (!cam) return;
    f > 0 ? cam.animatedZoom({ duration: 250 }) : f < 0 ? cam.animatedUnzoom({ duration: 250 }) : cam.animatedReset({ duration: 400 });
  };

  const S = st.current;
  return (
    <div className="workspace">
      <aside className="ws-side">
        <label className="sr" htmlFor="netzsuche">Search</label>
        <input id="netzsuche" className="search" placeholder="Name, handle, plate, keyword …" value={q} onChange={(e) => setQ(e.target.value)} />
        {hits && (
          <div style={{ marginTop: 8 }}>
            {hits.persons.map((p) => (
              <button key={p.id} className="btn ghost sm" style={{ margin: 2 }} onClick={() => selectPerson(p.id)}>
                {p.name}
              </button>
            ))}
            <ul className="plist" style={{ marginTop: 6 }}>
              {hits.units.map((u) => (
                <li key={u.id}>
                  <button onClick={() => showInGraph({ title: u.title, nodes: [`u:${u.id}`], kind: "search" }, `u:${u.id}`)}>
                    <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{u.title}</span>
                    <span className="cnt">{data?.doc_types[u.doc_type] ?? u.doc_type}</span>
                  </button>
                </li>
              ))}
            </ul>
            {!hits.units.length && !hits.persons.length && <div className="muted small">No matches.</div>}
          </div>
        )}

        <h4 className="h4">People (A–Z)</h4>
        <ul className="plist">
          {sortedPersons.map((p) => {
            const v = pstatus(p.id);
            return (
              <li key={p.id}>
                <button className={`${S.selected === `p:${p.id}` ? "on" : ""}`} onClick={() => selectPerson(p.id)}>
                  <span className={p.suspect ? "sus" : ""}>
                    {p.suspect ? "● " : ""}
                    {p.name}
                  </span>
                  <span className="cnt">
                    {v === "cleared" ? "cleared" : v === "culprit" ? "hypothesis" : v === "unresolved" ? "open" : ""} {p.unit_count}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
        <div className="tiny muted" style={{ marginTop: 4 }}>● = one of the eight people under review · number = linked units</div>

        <h4 className="h4">Document types</h4>
        <div className="filters">
          {docCounts.map(([d, n]) => (
            <button key={d} className={`fchip ${S.docOff.has(d) ? "off" : ""}`} onClick={() => toggle(S.docOff, d)} aria-pressed={!S.docOff.has(d)}>
              <i style={{ background: DOC_COLOR[d] }} />
              {data?.doc_types[d] ?? d} <span className="muted">{n}</span>
            </button>
          ))}
        </div>
        <h4 className="h4">Relation types (Bob, quote-verified)</h4>
        <div className="filters">
          {relCounts.length === 0 && <span className="muted small">No relations yet – analysis pending.</span>}
          {relCounts.map(([t, n]) => (
            <button key={t} className={`fchip ${S.relOff.has(t) ? "off" : ""}`} onClick={() => toggle(S.relOff, t)} aria-pressed={!S.relOff.has(t)}>
              <i style={{ background: REL_COLOR[t] ?? "#5a6a82" }} />
              {relLabel(t)} <span className="muted">{n}</span>
            </button>
          ))}
        </div>
        <h4 className="h4">Display</h4>
        <label className="small row" style={{ gap: 6 }}>
          <input type="checkbox" checked={S.showBezug} onChange={() => { S.showBezug = !S.showBezug; sigmaRef.current?.refresh({ skipIndexation: true }); rerender(); }} />
          Show person links of the selection
        </label>
        <label className="small row" style={{ gap: 6 }}>
          <input type="checkbox" checked={S.showEntities} onChange={() => { S.showEntities = !S.showEntities; sigmaRef.current?.refresh({ skipIndexation: true }); rerender(); }} />
          Entities (places, systems, vehicles …)
        </label>
        <h4 className="h4">Legend</h4>
        <div className="legend">
          <div><i style={{ background: C.suspect }} />person under review</div>
          <div><i style={{ background: C.person }} />other person</div>
          <div><i style={{ background: C.belastend }} />evidence: incriminating (Bob label)</div>
          <div><i style={{ background: C.entlastend }} />evidence: exonerating / explanation</div>
          <div><i style={{ background: C.offen }} />open question / contradiction</div>
          <div><i style={{ background: C.neutral }} />relevant, neutral</div>
          <div><i style={{ background: C.reviewed }} />reviewed by Bob, unremarkable</div>
          <div><i style={{ background: C.none }} />not yet reviewed</div>
          <div><i style={{ background: C.entity }} />entity (Bob)</div>
          <div><i className="line" style={{ background: "#f1c21b" }} />evidence chain (numbered)</div>
        </div>
        {data && (
          <div className="tiny muted" style={{ marginTop: 12 }}>
            {data.stats.nodes.toLocaleString("en-US")} nodes · {data.stats.edges.toLocaleString("en-US")} edges · {data.stats.relations} Bob relations
          </div>
        )}
      </aside>
      <div className="ws-canvas">
        {err && <div className="notice bad" style={{ margin: 20 }}>{err}</div>}
        {!data && !err && <div style={{ padding: 20, color: "#c6c6c6" }}>Loading evidence network …</div>}
        <div ref={holder} className="sigma" />
        <canvas ref={overlay} className="overlay" />
        <div className="focusbar">
          {focus && (
            <>
              <span className="focuschip">{focus.kind === "chain" ? "Evidence chain" : "Selection"}: {focus.title} · {focus.nodes.length} nodes</span>
              <button className="btn sm" onClick={() => setState({ focus: null, selected: null })}>Clear selection</button>
            </>
          )}
          {preview && <span className="focuschip info">Preview: structural links only, no Bob labels yet</span>}
        </div>
        <div className="zoomctl">
          <button onClick={() => zoom(1)} aria-label="Zoom in">+</button>
          <button onClick={() => zoom(-1)} aria-label="Zoom out">−</button>
          <button onClick={() => zoom(0)} aria-label="Fit to view">⤢</button>
        </div>
        {!selected && <div className="hint">Scroll to zoom · drag to pan · click a person or evidence node for connections and details</div>}
        {selected && data && graphRef.current && <DetailPanel id={selected} graph={graphRef.current} persons={persons} analysis={analysis} />}
      </div>
    </div>
  );
}
