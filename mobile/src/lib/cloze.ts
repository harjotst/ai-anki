// Cloze markup is authoring notation, not copy. The question side renders
// {{c1::...}} as [...] (the server does that); this is the other half: the
// ANSWER side, where the deletion is filled back in. Raw markers reaching a
// screen was the bug — a studying user was shown {{c1::fatty-acid synthesis}}.
export const clozeReveal = (text: string): string =>
  (text || "").replace(/\{\{c\d+::(.*?)(?:::[^}]*)?\}\}/g, "$1");

// What the answer side of any card should read: a basic card's back, a cloze
// card's front with its deletions restored — never an empty string, never
// markup. The back of a cloze, when present, is extra context, not the answer.
export const answerText = (card: { note_type?: string; front?: string; back?: string }): string =>
  card.note_type === "cloze" ? clozeReveal(card.front || "") : card.back || card.front || "";
