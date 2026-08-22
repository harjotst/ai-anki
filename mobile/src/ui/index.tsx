// Shared primitives: the same visual vocabulary as the web's ui.jsx and
// style.css, rendered natively. Icons are the identical stroke paths on the
// same 24px grid — no emoji, no icon font.
import React, {
  createContext, useCallback, useContext, useEffect, useRef, useState,
} from "react";
import {
  ColorValue, Modal, Pressable, ScrollView, Text, View, ViewStyle, TextStyle,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import Svg, { Circle, Path, Rect } from "react-native-svg";
import { font, radius, space, target, usePalette } from "../theme";

// --- icons -----------------------------------------------------------------

const PATHS: Record<string, React.ReactNode> = {
  plus: <Path d="M12 5v14M5 12h14" />,
  minus: <Path d="M5 12h14" />,
  x: <Path d="M6 6l12 12M18 6L6 18" />,
  chevR: <Path d="M9 6l6 6-6 6" />,
  chevL: <Path d="M15 6l-6 6 6 6" />,
  chevD: <Path d="M6 9l6 6 6-6" />,
  check: <Path d="M5 12.5l4.5 4.5L19 7.5" />,
  today: (
    <>
      <Rect x="4" y="5" width="16" height="16" rx="2.5" />
      <Path d="M4 10h16M8 3v4M16 3v4" />
      <Path d="M9 15.5l2 2 4-4" />
    </>
  ),
  decks: (
    <>
      <Path d="M12 3l9 5-9 5-9-5 9-5z" />
      <Path d="M3 13l9 5 9-5" />
    </>
  ),
  board: <Path d="M5 20v-8M12 20V5M19 20v-5" />,
  you: (
    <>
      <Circle cx="12" cy="8.5" r="3.5" />
      <Path d="M5 20c1.4-3.2 4-4.8 7-4.8s5.6 1.6 7 4.8" />
    </>
  ),
  dots: (
    <>
      <Circle cx="5" cy="12" r="1.1" fill="currentColor" stroke="none" />
      <Circle cx="12" cy="12" r="1.1" fill="currentColor" stroke="none" />
      <Circle cx="19" cy="12" r="1.1" fill="currentColor" stroke="none" />
    </>
  ),
  share: (
    <>
      <Circle cx="6" cy="12" r="2.4" />
      <Circle cx="17.5" cy="6" r="2.4" />
      <Circle cx="17.5" cy="18" r="2.4" />
      <Path d="M8.2 10.8l7-3.6M8.2 13.2l7 3.6" />
    </>
  ),
  download: (
    <>
      <Path d="M12 4v11M7.5 10.5L12 15l4.5-4.5" />
      <Path d="M5 19.5h14" />
    </>
  ),
  doc: (
    <>
      <Path d="M7 3.5h7l4 4V20a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 6 20V5a1.5 1.5 0 0 1 1-1.4z" />
      <Path d="M12 11v6M9 14h6" />
    </>
  ),
  copy: (
    <>
      <Rect x="9" y="9" width="11" height="11" rx="2" />
      <Path d="M5 15H4.5A1.5 1.5 0 0 1 3 13.5v-9A1.5 1.5 0 0 1 4.5 3h9A1.5 1.5 0 0 1 15 4.5V5" />
    </>
  ),
  edit: <Path d="M4 20l1-4L17.5 3.5a2.1 2.1 0 0 1 3 3L8 19l-4 1z" />,
  search: (
    <>
      <Circle cx="11" cy="11" r="6.5" />
      <Path d="M20 20l-4.2-4.2" />
    </>
  ),
  undo: <Path d="M8 5L3.5 9.5 8 14M4 9.5h10a6 6 0 0 1 0 12h-3" />,
  info: (
    <>
      <Circle cx="12" cy="12" r="9" />
      <Path d="M12 11v5M12 7.5v.5" />
    </>
  ),
};

export function Icon({ name, size = 22, color }: { name: string; size?: number; color?: ColorValue }) {
  const palette = usePalette();
  return (
    <Svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke={color ?? palette.text}
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      color={color ?? palette.text}
    >
      {PATHS[name]}
    </Svg>
  );
}

// --- text ------------------------------------------------------------------

type Variant = "statXl" | "display" | "title" | "heading" | "body" | "secondary" | "caption";

export function T({
  v = "body", color, style, children, ...rest
}: {
  v?: Variant; color?: string; style?: TextStyle | TextStyle[]; children?: React.ReactNode;
} & React.ComponentProps<typeof Text>) {
  const palette = usePalette();
  const base = v === "secondary" || v === "caption" ? palette.text2 : palette.text;
  return (
    <Text {...rest} style={[font(v) as TextStyle, { color: color ?? base }, style as any]}>
      {children}
    </Text>
  );
}

/** Caption in the uppercase register the web's .cap uses. */
export function Cap({ children, color, style }: { children: React.ReactNode; color?: string; style?: TextStyle }) {
  const palette = usePalette();
  return (
    <Text style={[font("caption") as TextStyle, { color: color ?? palette.text2, letterSpacing: 0.2 }, style]}>
      {children}
    </Text>
  );
}

// --- surfaces and controls -------------------------------------------------

export function Screen({ children, gap = space[3], style }: {
  children: React.ReactNode; gap?: number; style?: ViewStyle;
}) {
  const palette = usePalette();
  // The notch is not padding a screen may choose; every screen clears it.
  const insets = useSafeAreaInsets();
  return (
    <ScrollView
      style={{ flex: 1, backgroundColor: palette.bg }}
      contentContainerStyle={[
        { padding: space[3], gap, paddingTop: insets.top + space[2], paddingBottom: space[6] },
        style,
      ]}
      keyboardShouldPersistTaps="handled"
    >
      {children}
    </ScrollView>
  );
}

export function CardBox({ children, style }: { children: React.ReactNode; style?: ViewStyle }) {
  const palette = usePalette();
  return (
    <View style={[{
      backgroundColor: palette.surface, borderColor: palette.border, borderWidth: 1,
      borderRadius: radius.lg, padding: space[4],
    }, style]}>
      {children}
    </View>
  );
}

export function Button({
  title, onPress, kind = "primary", disabled, style,
}: {
  title: string; onPress: () => void; kind?: "primary" | "ghost" | "danger";
  disabled?: boolean; style?: ViewStyle;
}) {
  const palette = usePalette();
  const colors = {
    primary: { bg: palette.accent, fg: palette.onAccent, border: palette.accent },
    ghost: { bg: "transparent", fg: palette.text, border: palette.borderStrong },
    danger: { bg: "transparent", fg: palette.danger, border: palette.danger },
  }[kind];
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled}
      style={({ pressed }) => [{
        minHeight: target.min, borderRadius: radius.md, borderWidth: 1,
        borderColor: colors.border, backgroundColor: colors.bg,
        alignItems: "center", justifyContent: "center", paddingHorizontal: space[4],
        opacity: disabled ? 0.5 : pressed ? 0.75 : 1,
      }, style]}
    >
      <Text style={[font("heading") as TextStyle, { color: colors.fg }]}>{title}</Text>
    </Pressable>
  );
}

export function IconBtn({ name, onPress, label, color }: {
  name: string; onPress: () => void; label: string; color?: string;
}) {
  const palette = usePalette();
  return (
    <Pressable
      onPress={onPress}
      accessibilityLabel={label}
      style={({ pressed }) => ({
        width: target.min, height: target.min, borderRadius: radius.md,
        alignItems: "center", justifyContent: "center",
        backgroundColor: pressed ? palette.sunken : "transparent",
      })}
    >
      <Icon name={name} color={color ?? palette.text} />
    </Pressable>
  );
}

export function Pill({ text, accent }: { text: string; accent?: boolean }) {
  const palette = usePalette();
  return (
    <View style={{
      borderRadius: radius.pill, paddingHorizontal: 10, paddingVertical: 3,
      backgroundColor: accent ? palette.accentSoft : palette.sunken,
    }}>
      <Text style={[font("caption") as TextStyle, {
        color: accent ? palette.accent : palette.text2, fontVariant: ["tabular-nums"],
      }]}>
        {text}
      </Text>
    </View>
  );
}

export function NavRow({ onPress, children, right }: {
  onPress: () => void; children: React.ReactNode; right?: React.ReactNode;
}) {
  const palette = usePalette();
  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => ({
        minHeight: 56, flexDirection: "row", alignItems: "center", gap: space[3],
        backgroundColor: pressed ? palette.sunken : palette.surface,
        borderColor: palette.border, borderWidth: 1, borderRadius: radius.md,
        paddingHorizontal: space[4], paddingVertical: space[3],
      })}
    >
      <View style={{ flex: 1, gap: 2 }}>{children}</View>
      {right}
      <Icon name="chevR" size={16} color={palette.muted} />
    </Pressable>
  );
}

export function Seg({ options, value, onChange }: {
  options: [string, string][]; value: string; onChange: (key: string) => void;
}) {
  const palette = usePalette();
  return (
    <View style={{
      flexDirection: "row", backgroundColor: palette.sunken,
      borderRadius: radius.md, padding: 3, gap: 3,
    }}>
      {options.map(([key, label]) => (
        <Pressable
          key={key}
          onPress={() => onChange(key)}
          style={{
            flex: 1, minHeight: 38, alignItems: "center", justifyContent: "center",
            borderRadius: radius.sm,
            backgroundColor: key === value ? palette.surface : "transparent",
            borderWidth: key === value ? 1 : 0, borderColor: palette.border,
          }}
        >
          <Text style={[font("secondary") as TextStyle, {
            color: key === value ? palette.text : palette.text2,
            fontWeight: key === value ? "600" : "400",
          }]}>
            {label}
          </Text>
        </Pressable>
      ))}
    </View>
  );
}

export function Skeleton({ h = 56, r = radius.md }: { h?: number; r?: number }) {
  const palette = usePalette();
  return <View style={{ height: h, borderRadius: r, backgroundColor: palette.sunken }} />;
}

export function ErrorCard({ message, onRetry }: { message: string; onRetry?: () => void }) {
  const palette = usePalette();
  return (
    <View style={{
      flexDirection: "row", alignItems: "center", gap: space[3],
      backgroundColor: palette.dangerSoft, borderRadius: radius.md, padding: space[4],
    }}>
      <T v="secondary" style={{ flex: 1 }}>{message}</T>
      {onRetry && <Button title="Retry" kind="ghost" onPress={onRetry} />}
    </View>
  );
}

export function Sheet({ onClose, children }: { onClose: () => void; children: React.ReactNode }) {
  const palette = usePalette();
  return (
    <Modal transparent animationType="slide" onRequestClose={onClose}>
      <Pressable
        style={{ flex: 1, backgroundColor: "rgba(0,0,0,0.4)", justifyContent: "flex-end" }}
        onPress={onClose}
      >
        <Pressable onPress={() => {}} style={{
          backgroundColor: palette.surface, borderTopLeftRadius: radius.lg,
          borderTopRightRadius: radius.lg, padding: space[4], paddingBottom: space[5],
          gap: space[3], maxHeight: "85%",
        }}>
          <View style={{
            alignSelf: "center", width: 36, height: 4, borderRadius: radius.pill,
            backgroundColor: palette.borderStrong, marginBottom: space[1],
          }} />
          {children}
        </Pressable>
      </Pressable>
    </Modal>
  );
}

/** The one renderer for card text, same contract as the web's CardText. */
export function CardText({ text, size = 18 }: { text: string; size?: number }) {
  const palette = usePalette();
  return (
    <Text style={{ fontSize: size, lineHeight: size * 1.5, color: palette.text }}>
      {text}
    </Text>
  );
}

// --- toasts ----------------------------------------------------------------

type Toast = { id: number; message: string; action?: string; onAction?: () => void };
const ToastContext = createContext<(m: string, o?: { action?: string; onAction?: () => void; ttl?: number }) => void>(() => {});
export const useToast = () => useContext(ToastContext);

export function ToastHost({ children }: { children: React.ReactNode }) {
  const palette = usePalette();
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(0);

  const push = useCallback((message: string, { action, onAction, ttl = 4000 }: any = {}) => {
    const id = nextId.current++;
    setToasts((current) => [...current, { id, message, action, onAction }]);
    setTimeout(() => setToasts((current) => current.filter((t) => t.id !== id)), ttl);
  }, []);

  return (
    <ToastContext.Provider value={push}>
      <View style={{ flex: 1 }}>
        {children}
        <View pointerEvents="box-none" style={{
          position: "absolute", left: space[3], right: space[3], bottom: 90, gap: space[2],
        }}>
          {toasts.map((toast) => (
            <View key={toast.id} style={{
              flexDirection: "row", alignItems: "center", gap: space[3],
              backgroundColor: palette.text, borderRadius: radius.md,
              paddingHorizontal: space[4], paddingVertical: space[3],
            }}>
              <Text style={[font("secondary") as TextStyle, { color: palette.bg, flex: 1 }]}>
                {toast.message}
              </Text>
              {toast.action && (
                <Pressable
                  onPress={() => {
                    toast.onAction?.();
                    setToasts((current) => current.filter((t) => t.id !== toast.id));
                  }}
                  style={{ minHeight: 32, justifyContent: "center" }}
                >
                  <Text style={[font("secondary") as TextStyle, { color: palette.bg, fontWeight: "700" }]}>
                    {toast.action}
                  </Text>
                </Pressable>
              )}
            </View>
          ))}
        </View>
      </View>
    </ToastContext.Provider>
  );
}
