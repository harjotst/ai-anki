// Emits src/tokens.css and src/tokens.ts from ../tokens.json.
//
// One source, two renderers: the web reads the CSS variables, the future
// React Native app imports tokens.ts. Nothing else may hold a color — CI
// fails the build on any hex literal outside the token files, because the
// dual palette dies from one stray hex and that is a CI problem, not a
// discipline problem.
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const t = JSON.parse(readFileSync(join(root, "tokens.json"), "utf8"));

// Kebab-case with digits split too: heat0 -> heat-0, text2 -> text-2.
// Without the digit rule the variable a component reads does not exist and
// the browser renders transparent — silently.
const kebab = (s) =>
  s.replace(/[A-Z]/g, (c) => "-" + c.toLowerCase()).replace(/([a-z])(\d)/g, "$1-$2");
const vars = (palette) =>
  Object.entries(palette)
    .map(([k, v]) => `  --${kebab(k)}: ${v};`)
    .join("\n");

const typeVars = Object.entries(t.type)
  .filter(([, v]) => typeof v === "object")
  .map(
    ([k, v]) =>
      `  --type-${kebab(k)}: ${v.size}px; --lh-${kebab(k)}: ${v.line}px; --w-${kebab(k)}: ${v.weight};`
  )
  .join("\n");

const css = `/* GENERATED from tokens.json by scripts/emit-tokens.mjs — do not hand-edit.
 * Any hex literal outside the token files fails CI. */
:root {
${vars(t.color.light)}
  --font-sans: ${t.type.sans};
  --font-mono: ${t.type.mono};
${typeVars}
${t.space.map((v, i) => `  --space-${i + 1}: ${v}px;`).join("\n")}
${Object.entries(t.radius)
  .map(([k, v]) => `  --radius-${k}: ${v}px;`)
  .join("\n")}
  --target-min: ${t.target.min}px;
  --target-rating: ${t.target.rating}px;
}

/* Dark: the system preference, unless the person chose light explicitly. */
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
${vars(t.color.dark)}
  }
}
/* The explicit choice, which beats the system either way. */
:root[data-theme="dark"] {
${vars(t.color.dark)}
}
`;
writeFileSync(join(root, "src", "tokens.css"), css);

const ts = `// GENERATED from tokens.json by scripts/emit-tokens.mjs — do not hand-edit.
// The React Native theme object: plain values, no CSS.
export const tokens = ${JSON.stringify(t, null, 2)} as const;
export type Tokens = typeof tokens;
`;
writeFileSync(join(root, "src", "tokens.ts"), ts);
console.log("emitted src/tokens.css and src/tokens.ts");
