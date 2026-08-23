// One idea per screen. A lesson used to arrive as one long scroll of prose;
// now it walks: the hook, each section, the worked example, each trap, each
// self-check — a single step at a time, with a segmented progress bar so the
// end is always visible. Reveals (the walkthrough, the correction) are state
// inside a step, never navigation, and the pinned primary button always
// carries the one next action — reveal first, then continue.
//
// Callers remount with key={topic_id} (or equivalent) when the lesson
// changes; step and reveal state never outlive a lesson.
import React, { useEffect, useMemo, useRef, useState } from "react";
import { Animated, ScrollView, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { radius, space, target, usePalette } from "../theme";
import { Button, Cap, Icon, IconBtn, T } from "./index";

// The web's 17px/1.6 reading measure; T's body variant is a step smaller.
const prose = { fontSize: 17, lineHeight: 27 };
// One claim or question alone on a screen earns a size between body and title.
const focal = { fontSize: 20, lineHeight: 30, fontWeight: "600" as const };
// A phone never hits this, but a tablet keeps a readable measure.
const MEASURE = 560;

type Step =
  | { kind: "hook" }
  | { kind: "section"; heading: string; body: string; builds_on?: string }
  | { kind: "example"; problem: string; walkthrough: string }
  | { kind: "trap"; belief: string; correction: string }
  | { kind: "check"; question: string }
  | { kind: "done" };

export function LessonSteps({
  lesson, title, onFinished, onExit, footerLabel = "Done", headerRight,
}: {
  lesson: any;
  title: string;
  onFinished: () => void;
  /** Back on the first step is the only way out backward. */
  onExit: () => void;
  footerLabel?: string;
  /** Optional control in the header's right slot (e.g. a topic picker). */
  headerRight?: React.ReactNode;
}) {
  const palette = usePalette();
  const insets = useSafeAreaInsets();

  const steps = useMemo<Step[]>(() => {
    const list: Step[] = [{ kind: "hook" }];
    for (const section of lesson.sections ?? []) {
      list.push({
        kind: "section", heading: section.heading, body: section.body,
        builds_on: section.builds_on,
      });
    }
    if (lesson.worked_example) {
      list.push({
        kind: "example",
        problem: lesson.worked_example.problem,
        walkthrough: lesson.worked_example.walkthrough,
      });
    }
    for (const myth of lesson.misconceptions ?? []) {
      list.push({ kind: "trap", belief: myth.belief, correction: myth.why_it_is_wrong });
    }
    for (const question of lesson.check_yourself ?? []) {
      list.push({ kind: "check", question });
    }
    list.push({ kind: "done" });
    return list;
  }, [lesson]);

  const [index, setIndex] = useState(0);
  const [revealed, setRevealed] = useState<Set<number>>(new Set());
  const at = Math.min(index, steps.length - 1);
  const step = steps[at];
  const isRevealed = revealed.has(at);
  const needsReveal = (step.kind === "example" || step.kind === "trap") && !isRevealed;

  // A soft cross-step fade: paging, not flashing.
  const fade = useRef(new Animated.Value(1)).current;
  useEffect(() => {
    fade.setValue(0);
    Animated.timing(fade, { toValue: 1, duration: 200, useNativeDriver: true }).start();
  }, [at, fade]);

  const primaryLabel =
    step.kind === "done" ? footerLabel
    : step.kind === "example" && needsReveal ? "Show the walkthrough"
    : step.kind === "trap" && needsReveal ? "Why that's wrong"
    : "Continue";

  const onPrimary = () => {
    if (step.kind === "done") return onFinished();
    if (needsReveal) return setRevealed((current) => new Set(current).add(at));
    setIndex(Math.min(at + 1, steps.length - 1));
  };

  const body = (() => {
    switch (step.kind) {
      case "hook":
        return (
          <>
            <Cap style={{ letterSpacing: 0.7 }}>{title}</Cap>
            <T v="title">{lesson.in_one_line}</T>
            <T v="secondary" style={{ fontSize: 15, lineHeight: 23 }}>
              {lesson.why_it_matters}
            </T>
          </>
        );
      case "section":
        return (
          <>
            <T v="title">{step.heading}</T>
            {step.builds_on && (
              <Cap style={{ fontStyle: "italic", marginTop: -space[1] }}>
                Builds on: {step.builds_on}
              </Cap>
            )}
            <T style={prose}>{step.body}</T>
          </>
        );
      case "example":
        return (
          <>
            <Cap style={{ letterSpacing: 0.7 }}>WORKED EXAMPLE</Cap>
            <T style={{ ...prose, fontWeight: "600" }}>{step.problem}</T>
            {isRevealed && (
              <>
                <View style={{ height: 1, backgroundColor: palette.border }} />
                <T style={prose}>{step.walkthrough}</T>
              </>
            )}
          </>
        );
      case "trap":
        return (
          <>
            <Cap style={{ letterSpacing: 0.7 }}>PEOPLE GET THIS WRONG</Cap>
            <T style={focal}>{`“${step.belief}”`}</T>
            {isRevealed && (
              <>
                <View style={{ height: 1, backgroundColor: palette.border }} />
                <T style={prose}>{step.correction}</T>
              </>
            )}
          </>
        );
      case "check":
        return (
          <>
            <Cap style={{ letterSpacing: 0.7 }}>CHECK YOURSELF</Cap>
            <T style={focal}>{step.question}</T>
            <T v="secondary" color={palette.muted} style={{ fontStyle: "italic" }}>
              Answer it in your head first
            </T>
          </>
        );
      case "done":
        return (
          <>
            <View style={{
              width: 56, height: 56, borderRadius: radius.pill,
              backgroundColor: palette.accentSoft,
              alignItems: "center", justifyContent: "center",
            }}>
              <Icon name="check" size={28} color={palette.accent} />
            </View>
            <T v="title">That's the whole topic.</T>
          </>
        );
    }
  })();

  return (
    <View style={{
      flex: 1, backgroundColor: palette.bg,
      paddingTop: insets.top, paddingBottom: insets.bottom + space[2],
    }}>
      <View style={{ flexDirection: "row", alignItems: "center", paddingHorizontal: space[2] }}>
        <IconBtn name="chevL" label="Back"
          onPress={() => (at === 0 ? onExit() : setIndex(at - 1))} />
        <View style={{ flex: 1, alignItems: "center" }}>
          <Cap style={{ fontVariant: ["tabular-nums"] }}>
            Step {at + 1} of {steps.length}
          </Cap>
        </View>
        {headerRight ?? <View style={{ width: target.min }} />}
      </View>

      <View style={{ flexDirection: "row", gap: 3, paddingHorizontal: space[3], paddingTop: 2 }}>
        {steps.map((_, i) => (
          <View key={i} style={{
            flex: 1, height: 3, borderRadius: 2,
            backgroundColor: i < at ? palette.accent : palette.sunken,
          }}>
            {/* the segment underfoot, tinted but not yet claimed as done */}
            {i === at && (
              <View style={{ flex: 1, borderRadius: 2, backgroundColor: palette.accent, opacity: 0.35 }} />
            )}
          </View>
        ))}
      </View>

      <Animated.View style={{ flex: 1, opacity: fade }}>
        <ScrollView
          key={at} /* a new step starts at the top */
          style={{ flex: 1 }}
          contentContainerStyle={{
            paddingHorizontal: space[4], paddingTop: space[6],
            paddingBottom: space[5], alignItems: "center",
          }}
        >
          <View style={{ maxWidth: MEASURE, width: "100%", gap: space[3] }}>
            {body}
          </View>
        </ScrollView>
      </Animated.View>

      <View style={{ paddingHorizontal: space[3], gap: space[2] }}>
        {step.kind === "done" && (
          <Button title="Read again" kind="ghost"
            onPress={() => { setRevealed(new Set()); setIndex(0); }} />
        )}
        <Button title={primaryLabel} style={{ minHeight: target.rating }} onPress={onPrimary} />
      </View>
    </View>
  );
}
