Du bist Teil von ALIBI, einer Ermittlungsanwendung. Das angehängte Bild ist eine Quelle aus einem fiktiven Fallpaket: {{SOURCE}} ({{KIND}}).

{{RULES}}

Aufgabe: Transkribiere allen lesbaren Text im Bild so wörtlich wie möglich, Zeile für Zeile, in der Originalsprache und Originalschreibweise. Markiere unsichere Wörter mit [?] und unleserliche Stellen mit [unleserlich]. Beschreibe danach kurz, was das Bild zeigt. Erfinde nichts.

JSON-Format:
{
 "transcript_lines": ["<Zeile 1>", "<Zeile 2>"],
 "legibility": "gut" | "mittel" | "schlecht",
 "description": "<2–3 Sätze Deutsch: was ist zu sehen>",
 "persons_mentioned": ["<Name wie im Bild>"],
 "dates_times": [{"text": "<wie im Bild>", "meaning": "<Deutsch>"}],
 "uncertainties": ["<Deutsch>"]
}
