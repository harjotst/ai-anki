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

// The answer side the way Anki shows it: the question's own sentence with
// each deletion filled back in where the blank was, so the eye lands on the
// answer in context instead of reading the sentence twice.
export type ClozeSegment = { text: string; answer: boolean };
export const clozeSegments = (text: string): ClozeSegment[] => {
  const segments: ClozeSegment[] = [];
  const pattern = /\{\{c\d+::(.*?)(?:::[^}]*)?\}\}/g;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = pattern.exec(text || ""))) {
    if (m.index > last) segments.push({ text: text.slice(last, m.index), answer: false });
    segments.push({ text: m[1], answer: true });
    last = m.index + m[0].length;
  }
  if (last < (text || "").length) segments.push({ text: text.slice(last), answer: false });
  return segments;
};
