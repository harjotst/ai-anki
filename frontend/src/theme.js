// The theme choice: system by default, with an explicit override that beats it.
// Stored locally — a theme is a device preference, not account data.
const KEY = "ai_anki_theme";

export function themeSetting() {
  return window.localStorage.getItem(KEY) || "system";
}

export function applyTheme(setting) {
  if (setting === "system") {
    window.localStorage.removeItem(KEY);
    document.documentElement.removeAttribute("data-theme");
  } else {
    window.localStorage.setItem(KEY, setting);
    document.documentElement.setAttribute("data-theme", setting);
  }
}

export function initTheme() {
  const chosen = window.localStorage.getItem(KEY);
  if (chosen) document.documentElement.setAttribute("data-theme", chosen);
}
