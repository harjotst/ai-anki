// The theme: system by default, with an explicit override that beats it —
// the same contract as the web's theme.js, stored on the device because a
// theme is a device preference, not account data.
import AsyncStorage from "@react-native-async-storage/async-storage";
import React, { createContext, useContext, useEffect, useState } from "react";
import { useColorScheme } from "react-native";
import { tokens } from "./tokens";

export { tokens };
// Widened to plain strings: the two palettes are the same shape with
// different literals, and a Palette is whichever one is active.
export type Palette = { [K in keyof typeof tokens.color.light]: string };
export type ThemeSetting = "system" | "light" | "dark";

const KEY = "ai_anki_theme";
const ThemeContext = createContext<{
  setting: ThemeSetting;
  setSetting: (s: ThemeSetting) => void;
}>({ setting: "system", setSetting: () => {} });

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [setting, set] = useState<ThemeSetting>("system");
  useEffect(() => {
    AsyncStorage.getItem(KEY).then((stored) => {
      if (stored === "light" || stored === "dark") set(stored);
    });
  }, []);
  const setSetting = (next: ThemeSetting) => {
    set(next);
    if (next === "system") void AsyncStorage.removeItem(KEY);
    else void AsyncStorage.setItem(KEY, next);
  };
  return (
    <ThemeContext.Provider value={{ setting, setSetting }}>
      {children}
    </ThemeContext.Provider>
  );
}

export const useThemeSetting = () => useContext(ThemeContext);

export function usePalette(): Palette {
  const system = useColorScheme();
  const { setting } = useThemeSetting();
  const dark = setting === "dark" || (setting === "system" && system === "dark");
  return dark ? tokens.color.dark : tokens.color.light;
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
