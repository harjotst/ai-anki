// Scientific notation in running text: $V_{max}$, $k_{cat}/K_m$, $Ca^{2+}$.
//
// Full LaTeX needs a web view per formula; what the material actually uses
// is subscripts, superscripts, Greek letters and arrows — all of which
// render natively. Dollar-delimited spans use LaTeX-style _{} and ^{}; text
// outside spans gets a conservative upgrade of well-known tokens (Vmax, Km,
// kcat, Ca2+…) so content written before this existed improves too.
import React from "react";
import { Text, TextStyle } from "react-native";

type Piece = { text: string; kind: "plain" | "sub" | "sup" };

const GREEK: Record<string, string> = {
  alpha: "α", beta: "β", gamma: "γ", delta: "δ", Delta: "Δ", epsilon: "ε",
  theta: "θ", kappa: "κ", lambda: "λ", mu: "μ", pi: "π", rho: "ρ",
  sigma: "σ", tau: "τ", phi: "φ", omega: "ω", Omega: "Ω",
  rightarrow: "→", leftrightarrow: "⇌", rightleftharpoons: "⇌", pm: "±",
  times: "×", cdot: "·", degree: "°", dagger: "‡", infty: "∞",
};

const SUP_CHARS: Record<string, string> = {
  "0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴", "5": "⁵", "6": "⁶",
  "7": "⁷", "8": "⁸", "9": "⁹", "+": "⁺", "-": "⁻", "−": "⁻", "n": "ⁿ", "i": "ⁱ",
};

/** Superscripts that transliterate fully to Unicode need no styling at all
 *  — and Unicode beats a shrunken span, which cannot rise off the baseline. */
function asUnicodeSup(text: string): string | null {
  let out = "";
  for (const ch of text) {
    const mapped = SUP_CHARS[ch];
    if (!mapped) return null;
    out += mapped;
  }
  return out;
}

function mathPieces(body: string): Piece[] {
  // Inside a $...$ span: _{...} ^{...} _x ^x, \greek, everything else plain.
  const pieces: Piece[] = [];
  let i = 0;
  const push = (text: string, kind: Piece["kind"]) => {
    if (!text) return;
    if (kind === "sup") {
      const unicode = asUnicodeSup(text);
      if (unicode) return void pieces.push({ text: unicode, kind: "plain" });
    }
    pieces.push({ text, kind });
  };
  while (i < body.length) {
    const ch = body[i];
    if (ch === "_" || ch === "^") {
      const kind = ch === "_" ? "sub" : "sup";
      if (body[i + 1] === "{") {
        const end = body.indexOf("}", i + 2);
        if (end === -1) { push(body.slice(i), "plain"); break; }
        push(body.slice(i + 2, end), kind);
        i = end + 1;
      } else {
        push(body[i + 1] ?? "", kind);
        i += 2;
      }
    } else if (ch === "\\") {
      const word = /^[A-Za-z]+/.exec(body.slice(i + 1))?.[0] ?? "";
      push(GREEK[word] ?? word, "plain");
      i += 1 + word.length;
    } else {
      let j = i;
      while (j < body.length && !"_^\\".includes(body[j])) j += 1;
      push(body.slice(i, j), "plain");
      i = j;
    }
  }
  return pieces;
}

// Notation that predates the markup, upgraded conservatively. Word-bounded,
// case-exact, and only tokens that cannot mean anything else in this corpus.
const KNOWN: [RegExp, (m: RegExpExecArray) => Piece[]][] = [
  [/\bV_?max\b/g, () => [{ text: "V", kind: "plain" }, { text: "max", kind: "sub" }]],
  [/\bk_?cat\b/g, () => [{ text: "k", kind: "plain" }, { text: "cat", kind: "sub" }]],
  [/\bK_?([mdiaMDI])\b/g, (m) => [{ text: "K", kind: "plain" }, { text: m[1].toLowerCase(), kind: "sub" }]],
  [/\bpKa\b/g, () => [{ text: "pK", kind: "plain" }, { text: "a", kind: "sub" }]],
  [/\b(IC|EC|LD|TD)50\b/g, (m) => [{ text: m[1], kind: "plain" }, { text: "50", kind: "sub" }]],
  [/\bt1\/2\b/g, () => [{ text: "t", kind: "plain" }, { text: "1/2", kind: "sub" }]],
  [/\b(Ca|Mg|Zn|Fe|Cu)2\+/g, (m) => [{ text: m[1] + "²⁺", kind: "plain" }]],
  [/\b(Na|K|H|Li)\+(?!\w)/g, (m) => [{ text: m[1] + "⁺", kind: "plain" }]],
  [/\b(Cl|OH|HCO3|I)-(?!\w)/g, (m) => [{ text: m[1] + "⁻", kind: "plain" }]],
  [/\b(CO|O|H2O|NO|N)2\b/g, (m) => [{ text: m[1] + "₂", kind: "plain" }]],
  [/\bs-1\b/g, () => [{ text: "s⁻¹", kind: "plain" }]],
  [/\bM-1s-1\b/g, () => [{ text: "M⁻¹s⁻¹", kind: "plain" }]],
];

function upgrade(plain: string): Piece[] {
  let pieces: Piece[] = [{ text: plain, kind: "plain" }];
  for (const [pattern, replace] of KNOWN) {
    const next: Piece[] = [];
    for (const piece of pieces) {
      if (piece.kind !== "plain") { next.push(piece); continue; }
      let last = 0;
      pattern.lastIndex = 0;
      let m: RegExpExecArray | null;
      while ((m = pattern.exec(piece.text))) {
        if (m.index > last) next.push({ text: piece.text.slice(last, m.index), kind: "plain" });
        next.push(...replace(m));
        last = m.index + m[0].length;
      }
      if (last < piece.text.length) next.push({ text: piece.text.slice(last), kind: "plain" });
    }
    pieces = next;
  }
  return pieces;
}

export function sciPieces(text: string): Piece[] {
  const pieces: Piece[] = [];
  // Only spans with math structure are formulas; "$5, then $6" is money.
  const parts = text.split(/\$([^$]*[_^\\][^$]*)\$/g);
  parts.forEach((part, index) => {
    if (index % 2 === 1) pieces.push(...mathPieces(part));
    else pieces.push(...upgrade(part));
  });
  return pieces.filter((piece) => piece.text.length > 0);
}

/** The same text as something a voice can say: markup dropped, notation
 *  spelled the way it is read aloud. */
export function sciSpeakable(text: string): string {
  return sciPieces(text)
    .map((piece) => piece.text)
    .join("")
    .replace(/⁻¹/g, " to the minus one")
    .replace(/²⁺/g, " two plus")
    .replace(/⁺/g, " plus")
    .replace(/⁻/g, " minus")
    .replace(/₂/g, " two")
    .replace(/→/g, " gives ")
    .replace(/⇌/g, " in equilibrium with ");
}

/** Text with real notation. Drop-in for a plain <Text>. */
export function Sci({ text, style, subScale = 0.72 }: {
  text: string; style?: TextStyle | TextStyle[]; subScale?: number;
}) {
  const pieces = sciPieces(text);
  const base = Array.isArray(style) ? Object.assign({}, ...style) : style || {};
  const small = Math.round((base.fontSize ?? 16) * subScale);
  return (
    <Text style={style}>
      {pieces.map((piece, index) =>
        piece.kind === "plain" ? (
          <Text key={index}>{piece.text}</Text>
        ) : (
          // Nested small text sits on the shared baseline, which reads as a
          // subscript; superscripts that could not become Unicode land here
          // too, and the baseline is the honest compromise.
          <Text key={index} style={{ fontSize: small }}>{piece.text}</Text>
        )
      )}
    </Text>
  );
}


// --- word-level rendering, for a voice to follow -------------------------

export type SciWord = { pieces: Piece[]; spoken: string };

/** Display words: pieces grouped between whitespace, sub/superscripts glued
 *  to the word they belong to. Each word knows how it is said aloud, which
 *  is what keeps the highlight aligned with the voice — the screen shows
 *  $V_{max}$ as one word even though the voice says two. */
export function sciWords(text: string): SciWord[] {
  const words: SciWord[] = [];
  let current: Piece[] = [];
  const flush = () => {
    if (!current.length) return;
    const joined = current.map((piece) => piece.text).join("");
    words.push({ pieces: current, spoken: speakableWord(joined) });
    current = [];
  };
  for (const piece of sciPieces(text)) {
    if (piece.kind !== "plain") {
      current.push(piece);
      continue;
    }
    const chunks = piece.text.split(/(\s+)/);
    for (const chunk of chunks) {
      if (!chunk) continue;
      if (/^\s+$/.test(chunk)) flush();
      else current.push({ text: chunk, kind: "plain" });
    }
  }
  flush();
  return words;
}

function speakableWord(text: string): string {
  return text
    .replace(/⁻¹/g, " to the minus one")
    .replace(/²⁺/g, " two plus")
    .replace(/⁺/g, " plus")
    .replace(/⁻/g, " minus")
    .replace(/₂/g, " two")
    .replace(/→/g, " gives ")
    .replace(/⇌/g, " in equilibrium with ")
    .trim() || text;
}

/** Sci, plus a highlighted word: the box that follows the voice. */
export function SciText({ text, style, highlight, accentSoft, accent }: {
  text: string;
  style?: TextStyle | TextStyle[];
  highlight?: number;
  accentSoft?: string;
  accent?: string;
}) {
  const words = sciWords(text);
  const base = Array.isArray(style) ? Object.assign({}, ...style) : style || {};
  const small = Math.round((base.fontSize ?? 16) * 0.72);
  return (
    <Text style={style}>
      {words.map((word, w) => {
        const lit = w === highlight;
        const wordStyle = lit
          ? { backgroundColor: accentSoft, color: accent, fontWeight: "600" as const }
          : undefined;
        return (
          <Text key={w} style={wordStyle}>
            {word.pieces.map((piece, i) =>
              piece.kind === "plain" ? (
                <Text key={i}>{piece.text}</Text>
              ) : (
                <Text key={i} style={{ fontSize: small }}>{piece.text}</Text>
              )
            )}
            {w < words.length - 1 ? " " : ""}
          </Text>
        );
      })}
    </Text>
  );
}
