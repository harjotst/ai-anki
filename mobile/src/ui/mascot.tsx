// The mascot: an AI resident with a stethoscope, drawn once as vectors so
// it is crisp at every size. Colors come from the light palette on
// purpose — a mascot keeps its identity across themes, and the white body
// carries its own contrast on dark backgrounds.
import React from "react";
import Svg, { Circle, Line, Path, Rect } from "react-native-svg";
import { tokens } from "../theme";

export function Mascot({ size = 140 }: { size?: number }) {
  const c = tokens.color.light;
  return (
    <Svg width={size} height={(size * 250) / 260} viewBox="0 0 260 250">
      <Line x1="104" y1="14" x2="104" y2="30" stroke={c.text} strokeWidth={7} strokeLinecap="round" />
      <Circle cx="104" cy="12" r="9" fill={c.accent} />
      <Rect x="42" y="30" width="124" height="96" rx="30" fill={c.surface} stroke={c.text} strokeWidth={7} />
      <Rect x="58" y="50" width="92" height="56" rx="20" fill={c.text} />
      <Rect x="80" y="66" width="13" height="24" rx="6.5" fill={c.accentSoft} />
      <Rect x="115" y="66" width="13" height="24" rx="6.5" fill={c.accentSoft} />
      <Rect x="56" y="126" width="96" height="76" rx="26" fill={c.surface} stroke={c.text} strokeWidth={7} />
      <Circle cx="40" cy="80" r="7" fill={c.accent} />
      <Circle cx="168" cy="80" r="7" fill={c.accent} />
      <Path d="M38 84 C 30 112 52 136 104 145" fill="none" stroke={c.accent} strokeWidth={7} strokeLinecap="round" />
      <Path d="M170 84 C 178 110 156 138 112 145" fill="none" stroke={c.accent} strokeWidth={7} strokeLinecap="round" />
      <Path d="M106 145 C 126 190 182 194 206 142" fill="none" stroke={c.accent} strokeWidth={7} strokeLinecap="round" />
      <Path d="M152 150 L190 138" stroke={c.text} strokeWidth={13} strokeLinecap="round" />
      <Circle cx="206" cy="126" r="16" fill={c.accent} />
      <Circle cx="206" cy="126" r="7" fill={c.bg} />
      <Rect x="66" y="202" width="26" height="15" rx="7.5" fill={c.text} />
      <Rect x="112" y="202" width="26" height="15" rx="7.5" fill={c.text} />
    </Svg>
  );
}
