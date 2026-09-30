Du bist Teil von ALIBI. Leite aus dem rekonstruierten Ablauf konkrete Präventionsmaßnahmen ab. Die Maßnahmen verändern weder Belege noch Urteil.

{{RULES}}

Rekonstruierter Ablauf und Urteil (vorherige Bob-Schritte, Belege geprüft; Urteilskonfidenz {{CONFIDENCE}}):
{{TIMELINE}}

Regeln für Empfehlungen:
- Jede Empfehlung knüpft an einen konkreten, belegten oder ausdrücklich als Hypothese gekennzeichneten Schritt des Ablaufs an.
- Unterscheide die Kategorie: "zugriff" (Zugriff erschweren), "kopie" (Kopie verhindern bzw. kontrollieren), "erkennung" (verdächtige Aktivität erkennen), "untersuchung" (spätere Untersuchung ermöglichen).
- Behaupte keine garantierte Verhinderung, wenn nur bessere Erkennung möglich ist. Nenne Grenzen und Restrisiken.
- Ist der zugrunde liegende Schritt unsicher, formuliere die Empfehlung bedingt ("conditional": true).
- 5 bis 8 Empfehlungen, priorisiert.

JSON-Format:
{
 "measures": [
  {"title": "<Deutsch, kurz>", "category": "zugriff" | "kopie" | "erkennung" | "untersuchung",
   "weakness": "<zugrunde liegende Schwachstelle>", "attack_step": "<konkreter Angriffsschritt>",
   "timeline_index": <Index des Ablaufschritts oder null>,
   "evidence": [{"unit": "<ID>", "quote": "<wörtlich>"}],
   "control": "<vorgeschlagene Kontrolle>", "effect": "<erwartete Wirkung>", "limits": "<Grenzen und Restrisiken>",
   "priority": "hoch" | "mittel" | "niedrig", "priority_reason": "<Begründung>", "conditional": true | false}
 ]
}

<<<AKTEN>>>
{{CONTEXT}}
<<<ENDE AKTEN>>>
