Du bist Teil von ALIBI. Alle acht Personen wurden einzeln nach dem Prinzip „Entlastung zuerst“ geprüft. Vergleiche jetzt die verbleibenden Täterhypothesen anhand der belegten Zusammenhänge.

{{RULES}}

Begriffe – streng getrennt halten:
- Geschätzte Täterschaft (weight): relativer Vergleich der acht Täterhypothesen anhand der aktuellen Beweislage, unter der Fallannahme, dass eine der acht Personen die Tat begangen hat. Summe über alle acht = 1.
- Urteilskonfidenz (verdict_confidence): wie tragfähig das abschließende Urteil angesichts Belegen, Gegenargumenten und Lücken ist. Ein hoher relativer weight erzeugt NICHT automatisch eine hohe Urteilskonfidenz.
- Diese Werte sind begründete Modellschätzungen, keine kalibrierten Wahrscheinlichkeiten.
Keine Punktesumme wie „Motiv + Zugang = 90 %“. Berücksichtige: direkte vs. abgeleitete Belege, Zuverlässigkeit der Quellen, unabhängige Bestätigung, erklärte und unerklärte Widersprüche, fehlende Informationen, alternative Erklärungen.
Keine Person nur deshalb zum Täter machen, weil sie als letzte nicht entlastet ist. Keine Entlastung erzwingen. "cleared" nur mit belegter Entlastung.

Einzelprüfungen (Bob-Ergebnisse; alle Zitate darin wurden gegen die Originaldateien geprüft):
{{PERSONS}}

Ermittlungsrahmen:
{{FRAME}}

Aufgabe: Rekonstruiere den Ablauf (wer, wann, wie) und formuliere das Urteil.

JSON-Format:
{
 "leading": "<Kennung der führenden Täterhypothese>",
 "weights": [{"id": "<Kennung>", "weight": <0..1>, "why": "<Deutsch, 1 Satz>"}],
 "weights_basis": "<Deutsch: auf welchen Annahmen der Vergleich beruht>",
 "verdict_confidence": <0..1>,
 "confidence_reason": "<Deutsch: was trägt, was fehlt>",
 "persons": [
  {"id": "<Kennung>", "verdict": "culprit" | "cleared" | "unresolved",
   "reasoning_de": "<höchstens 2 Sätze Deutsch>",
   "reasoning_en": "<one or two short sentences in English, max 300 characters>",
   "evidence": [{"unit": "<ID>", "quote": "<wörtlich>", "claim_en": "<what this line shows, short English>", "claim_de": "<Deutsch>", "kind": "belastend" | "entlastend" | "kontext"}]}
 ],
 "timeline": [
  {"when": "<YYYY-MM-DDTHH:MM Europe/Zurich oder Zeitraum>", "when_note": "<Zeitbasis, ggf. Umrechnung mit Beleg>", "who": "<Kennung oder 'unbekannt'>", "what": "<Deutsch>", "how": "<Deutsch>", "status": "belegt" | "abgeleitet" | "hypothese", "evidence": [{"unit": "<ID>", "quote": "<wörtlich>"}]}
 ],
 "chains": [{"title": "<Deutsch>", "steps": [{"text": "<Deutsch>", "evidence": [{"unit": "<ID>", "quote": "<wörtlich>"}]}]}],
 "dismissed": [{"person": "<Kennung>", "suspicion": "<Deutsch>", "explanation": "<Deutsch>", "evidence": [{"unit": "<ID>", "quote": "<wörtlich>"}]}],
 "open_questions": ["<Deutsch>"]
}
Alle acht Personen genau einmal in "persons" und "weights". Genau eine Person hat verdict "culprit" – die führende Hypothese. Je Person 1–4 Belege, die das Urteil tragen; für "cleared" mindestens ein entlastender Beleg; bei "unresolved" nur echte Belege, sonst eine leere Liste.
