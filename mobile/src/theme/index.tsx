// The theme follows the system: light or dark, whichever the phone is in.
import { useColorScheme } from "react-native";
import { tokens } from "./tokens";

export { tokens };
// Widened to plain strings: the two palettes are the same shape with
// different literals, and a Palette is whichever one is active.
export type Palette = { [K in keyof typeof tokens.color.light]: string };

export function usePalette(): Palette {
  return useColorScheme() === "dark" ? tokens.color.dark : tokens.color.light;
}

/** One type style, sized from the scale. RN maps numeric weights onto the
 *  nearest face of the system font, so 620 is rounded to a real weight. */
export function font(name: keyof typeof tokens.type) {
  const t = tokens.type[name];
  if (typeof t === "string") return {};
  return {
    fontSize: t.size,
    lineHeight: t.line,
    fontWeight: String(Math.round(t.weight / 100) * 100) as
      | "400" | "500" | "600" | "700",
  };
}

export const space = tokens.space;
export const radius = tokens.radius;
export const target = tokens.target;
