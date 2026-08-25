// Read this page to me — inside the page, not instead of it.
//
// The page's own typeset text stays on screen; a box follows the word being
// spoken, and a pinned bar under the content carries play, scrub and
// restart so nothing worth reaching ever needs a scroll. The synthesizer
// cannot seek inside an utterance, so scrubbing restarts speech at the
// chosen word; boundary events arrive relative to whatever substring is
// speaking, and `spokenFrom` maps them back onto the whole passage.
import Slider from "@react-native-community/slider";
import * as Speech from "expo-speech";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import React from "react";
import { Platform, View } from "react-native";
import { radius, space, target, usePalette } from "../theme";
import { IconBtn } from "./index";
import { sciWords } from "./sci";

export type ReadAloudControl = {
  /** Whether the voice UI is on screen at all (playing, paused, or done). */
  active: boolean;
  state: "idle" | "playing" | "paused" | "done";
  toggle: () => void;
  restart: () => void;
  seek: (word: number) => void;
  /** Grabbing the scrubber: the voice pauses where it was. */
  beginScrub: () => void;
  /** Dragging it: the box rides the thumb, silently. */
  preview: (word: number) => void;
  current: number | null;
  total: number;
  /** The highlight for one part of the page, in that part's own word
   *  numbering — undefined when the voice is elsewhere. */
  highlightFor: (part: number) => number | undefined;
};

export function useReadAloud(parts: string[]): ReadAloudControl {
  const built = useMemo(() => {
    const perPart = parts.map((part) => sciWords(part));
    const flat = perPart.flat();
    const ranges: [number, number][] = [];
    let n = 0;
    perPart.forEach((words) => {
      ranges.push([n, n + words.length]);
      n += words.length;
    });
    const starts: number[] = [];
    let spoken = "";
    flat.forEach((word, index) => {
      starts.push(index === 0 ? 0 : spoken.length + 1);
      spoken = index === 0 ? word.spoken : `${spoken} ${word.spoken}`;
    });
    return { spoken, starts, ranges, total: flat.length };
  }, [parts]);

  const [state, setState] = useState<"idle" | "playing" | "paused" | "done">("idle");
  const [current, setCurrent] = useState<number | null>(null);
  const spokenFrom = useRef(0);
  const voice = useRef<string | undefined>(undefined);
  // Stopping an utterance makes iOS fire its completion callback anyway,
  // AFTER the replacement has started — a scrub would end with the old
  // utterance's "done" resetting the new one's state. Every utterance gets
  // a generation; callbacks from a superseded one are ignored.
  const generation = useRef(0);

  useEffect(() => {
    Speech.getAvailableVoicesAsync()
      .then((all) => {
        // Premium beats enhanced beats compact. expo-speech reports premium
        // voices as merely "Enhanced", but their identifiers say what they
        // are: com.apple.voice.premium.en-US.Ava.
        const en = all.filter((v) => v.language?.startsWith("en"));
        const premium = en.find((v) => v.identifier?.includes(".premium."));
        const enhanced = en.find(
          (v) => String(v.quality).toLowerCase() === "enhanced"
        );
        voice.current = (premium ?? enhanced ?? en[0])?.identifier;
      })
      .catch(() => {});
  }, []);

  // New content under the voice — a step change, a reveal — stops it.
  useEffect(() => {
    generation.current += 1;
    Speech.stop();
    setState("idle");
    setCurrent(null);
    return () => {
      generation.current += 1;
      void Speech.stop();
    };
  }, [built.spoken]);

  const wordAt = useCallback((charIndex: number) => {
    const absolute = spokenFrom.current + charIndex;
    for (let i = built.starts.length - 1; i >= 0; i--) {
      if (built.starts[i] <= absolute) return i;
    }
    return 0;
  }, [built.starts]);

  const speakFrom = useCallback((wordIndex: number) => {
    const mine = ++generation.current;
    Speech.stop();
    const start = built.starts[wordIndex] ?? 0;
    spokenFrom.current = start;
    setCurrent(wordIndex);
    setState("playing");
    Speech.speak(built.spoken.slice(start), {
      voice: voice.current,
      rate: 0.98,
      onBoundary: (event: any) => {
        if (generation.current !== mine) return;
        if (typeof event?.charIndex === "number") setCurrent(wordAt(event.charIndex));
      },
      onDone: () => {
        if (generation.current !== mine) return;
        setState((was) => (was === "playing" ? "done" : was));
        setCurrent(null);
      },
      onStopped: () => {
        // Only ever stale: a live utterance is stopped by its successor.
      },
      onError: () => {
        if (generation.current !== mine) return;
        setState("idle");
      },
    });
  }, [built, wordAt]);

  // Android's synthesizer has no pause/resume — Speech.pause() throws an
  // UnavailabilityError. There, pausing stops the utterance while keeping
  // the current word, and resuming restarts speech from that word. iOS
  // keeps the native pair.
  const pause = useCallback(() => {
    if (Platform.OS === "android") {
      // The stop's callbacks belong to no one: without a new generation,
      // the old utterance's "done" would wipe the paused state.
      generation.current += 1;
      Speech.stop();
    } else {
      Speech.pause();
    }
    setState("paused");
  }, []);

  const resume = useCallback(() => {
    if (Platform.OS === "android") {
      speakFrom(current ?? 0);
    } else {
      Speech.resume();
      setState("playing");
    }
  }, [speakFrom, current]);

  const toggle = useCallback(() => {
    if (state === "playing") pause();
    else if (state === "paused") resume();
    else speakFrom(0);
  }, [state, pause, resume, speakFrom]);

  const clamp = useCallback(
    (word: number) => Math.max(0, Math.min(built.total - 1, word)),
    [built.total]
  );

  return {
    active: state !== "idle",
    state,
    toggle,
    restart: useCallback(() => speakFrom(0), [speakFrom]),
    seek: useCallback((word: number) => speakFrom(clamp(word)), [speakFrom, clamp]),
    beginScrub: useCallback(() => {
      if (state === "playing") pause();
    }, [state, pause]),
    preview: useCallback((word: number) => setCurrent(clamp(word)), [clamp]),
    current,
    total: built.total,
    highlightFor: useCallback((part: number) => {
      if (current === null) return undefined;
      const range = built.ranges[part];
      if (!range || current < range[0] || current >= range[1]) return undefined;
      return current - range[0];
    }, [current, built.ranges]),
  };
}

/** The pinned control row: play/pause, the scrubber, from-the-top. */
export function ReadAloudBar({ ctl }: { ctl: ReadAloudControl }) {
  const palette = usePalette();
  return (
    <View style={{
      flexDirection: "row", alignItems: "center", gap: space[1],
      backgroundColor: palette.surface, borderColor: palette.border,
      borderWidth: 1, borderRadius: radius.md, paddingHorizontal: space[1],
      minHeight: target.min + 6,
    }}>
      <IconBtn
        name={ctl.state === "playing" ? "pause" : "sound"}
        label={ctl.state === "playing" ? "Pause" : "Listen"}
        onPress={ctl.toggle}
        color={palette.accent}
      />
      <Slider
        style={{ flex: 1 }}
        minimumValue={0}
        maximumValue={Math.max(0, ctl.total - 1)}
        step={1}
        value={ctl.current ?? 0}
        onSlidingStart={ctl.beginScrub}
        onValueChange={(v) => ctl.preview(Math.round(v))}
        onSlidingComplete={(v) => ctl.seek(Math.round(v))}
        minimumTrackTintColor={palette.accent}
        maximumTrackTintColor={palette.border}
        thumbTintColor={palette.accent}
      />
      <IconBtn name="undo" label="From the beginning" onPress={ctl.restart} />
    </View>
  );
}
