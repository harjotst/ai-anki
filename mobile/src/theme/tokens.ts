// GENERATED from tokens.json by scripts/emit-tokens.mjs — do not hand-edit.
// The React Native theme object: plain values, no CSS.
export const tokens = {
  "_": "Source of truth for every color and scale in ai-anki, web and mobile. Emitted as tokens.css and tokens.ts by scripts/emit-tokens.mjs. CI fails the build on any hex literal outside these generated files.",
  "color": {
    "light": {
      "bg": "#FAF9F7",
      "surface": "#FFFFFF",
      "sunken": "#F1EFEA",
      "border": "#E3E1DA",
      "borderStrong": "#C9C6BD",
      "text": "#1C1B18",
      "text2": "#605D55",
      "muted": "#8B877D",
      "accent": "#0E7C66",
      "accentHover": "#0A6353",
      "accentSoft": "#E3EFEB",
      "onAccent": "#FFFFFF",
      "success": "#33774F",
      "successSoft": "#E5F0E6",
      "danger": "#A83E36",
      "dangerSoft": "#F8E9E7",
      "warning": "#96690F",
      "warningSoft": "#F5EDDA",
      "heat0": "#EDEBE4",
      "heat1": "#CFE4DD",
      "heat2": "#9CCBBE",
      "heat3": "#5BA893",
      "heat4": "#0E7C66",
      "shadowSheet": "0 8px 24px rgba(0,0,0,0.18)"
    },
    "dark": {
      "bg": "#131311",
      "surface": "#1C1B18",
      "sunken": "#0D0D0B",
      "border": "#2B2A25",
      "borderStrong": "#3E3C35",
      "text": "#ECEAE3",
      "text2": "#A5A198",
      "muted": "#757168",
      "accent": "#3FBFA4",
      "accentHover": "#5ACDB4",
      "accentSoft": "#17342D",
      "onAccent": "#0A1613",
      "success": "#6FBE8B",
      "successSoft": "#1A2C20",
      "danger": "#E0776C",
      "dangerSoft": "#362019",
      "warning": "#D9AC55",
      "warningSoft": "#322A16",
      "heat0": "#1E1D1A",
      "heat1": "#1D3B33",
      "heat2": "#23594C",
      "heat3": "#2E8A73",
      "heat4": "#3FBFA4",
      "shadowSheet": "0 8px 24px rgba(0,0,0,0.45)"
    }
  },
  "type": {
    "sans": "\"Inter\", -apple-system, BlinkMacSystemFont, \"Segoe UI\", Roboto, system-ui, sans-serif",
    "mono": "ui-monospace, \"SF Mono\", Menlo, monospace",
    "statXl": {
      "size": 40,
      "line": 44,
      "weight": 650
    },
    "display": {
      "size": 32,
      "line": 38,
      "weight": 650
    },
    "title": {
      "size": 22,
      "line": 28,
      "weight": 620
    },
    "heading": {
      "size": 17,
      "line": 24,
      "weight": 620
    },
    "body": {
      "size": 16,
      "line": 24,
      "weight": 400
    },
    "secondary": {
      "size": 14,
      "line": 20,
      "weight": 400
    },
    "caption": {
      "size": 12,
      "line": 16,
      "weight": 500
    }
  },
  "space": [
    4,
    8,
    12,
    16,
    24,
    32,
    48
  ],
  "radius": {
    "sm": 6,
    "md": 10,
    "lg": 16,
    "pill": 999
  },
  "target": {
    "min": 44,
    "rating": 48
  }
} as const;
export type Tokens = typeof tokens;
