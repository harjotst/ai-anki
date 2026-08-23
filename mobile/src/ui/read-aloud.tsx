// Read this page to me.
//
// The voice is the system's; the machinery here is the part iOS does not
// give away: a box that follows the current word, and a scrubber that moves
// through the passage. The synthesizer cannot seek inside an utterance, so
// scrubbing restarts speech at the chosen word — boundary events arrive
// relative to whatever substring is being spoken, and `spokenFrom` maps them
// back onto the full text.
import Slider from "@react-native-community/slider";
import * as Speech from "expo-speech";
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Text, View } from "react-native";
import { radius, space, target, usePalette } from "../theme";
import { IconBtn } from "./index";
import { sciSpeakable } from "./sci";

type Word = { text: string; start: number };

function wordsOf(text: string): Word[] {
  const words: Word[] = [];
  const pattern = /\S+/g;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(text))) words.push({ text: match[0], start: match.index });
  return words;
}

export function ReadAloud({ text, fontSize = 17, lineHeight = 27 }: {
  text: string; fontSize?: number; lineHeight?: number;
}) {
  const palette = usePalette();
  const spoken = useMemo(() => sciSpeakable(text), [text]);
  const words = useMemo(() => wordsOf(spoken), [spoken]);

  const [state, setState] = useState<"idle" | "playing" | "paused" | "done">("idle");
  const [current, setCurrent] = useState<number | null>(null);
  const [scrubbing, setScrubbing] = useState(false);
  const spokenFrom = useRef(0);
  const voice = useRef<string | undefined>(undefined);

  useEffect(() => {
    // The most human voice on the device: enhanced beats default beats
    // whatever fell out of the list first.
    Speech.getAvailableVoicesAsync()
      .then((all) => {
        const en = all.filter((v) => v.language?.startsWith("en"));
        const best =
          en.find((v) => String(v.quality).toLowerCase() === "enhanced") ?? en[0];
        voice.current = best?.identifier;
      })
      .catch(() => {});
    return () => void Speech.stop();
  }, []);

  const wordAt = useCallback((charIndex: number) => {
    const absolute = spokenFrom.current + charIndex;
    for (let i = words.length - 1; i >= 0; i--) {
      if (words[i].start <= absolute) return i;
    }
    return 0;
  }, [words]);

  const speakFrom = useCallback((wordIndex: number) => {
    Speech.stop();
    const start = words[wordIndex]?.start ?? 0;
    spokenFrom.current = start;
    setCurrent(wordIndex);
    setState("playing");
    Speech.speak(spoken.slice(start), {
      voice: voice.current,
      rate: 0.98,
      onBoundary: (event: any) => {
        if (typeof event?.charIndex === "number") setCurrent(wordAt(event.charIndex));
      },
      onDone: () => {
        setState((was) => (was === "playing" ? "done" : was));
        setCurrent(null);
      },
      onStopped: () => {},
      onError: () => setState("idle"),
    });
  }, [spoken, words, wordAt]);

  const toggle = useCallback(() => {
    if (state === "playing") {
      Speech.pause();
      setState("paused");
    } else if (state === "paused") {
      Speech.resume();
      setState("playing");
    } else {
      speakFrom(0);
    }
  }, [state, speakFrom]);

  const restart = useCallback(() => speakFrom(0), [speakFrom]);

  return (
    <View style={{ gap: space[3] }}>
      <Text style={{ fontSize, lineHeight, color: palette.text }}>
        {words.map((word, index) => (
          <Text
            key={index}
            style={
              index === current
                ? {
                    backgroundColor: palette.accentSoft,
                    color: palette.accent,
                    fontWeight: "600",
                    borderRadius: radius.sm,
                  }
                : undefined
            }
          >
            {word.text}
            {index < words.length - 1 ? " " : ""}
          </Text>
        ))}
      </Text>

      <View style={{
        flexDirection: "row", alignItems: "center", gap: space[2],
        backgroundColor: palette.surface, borderColor: palette.border,
        borderWidth: 1, borderRadius: radius.md, paddingHorizontal: space[2],
        minHeight: target.min + 8,
      }}>
        <IconBtn
          name={state === "playing" ? "pause" : "sound"}
          label={state === "playing" ? "Pause" : "Listen"}
          onPress={toggle}
          color={palette.accent}
        />
        <Slider
          style={{ flex: 1 }}
          minimumValue={0}
          maximumValue={Math.max(0, words.length - 1)}
          step={1}
          value={current ?? 0}
          onSlidingStart={() => setScrubbing(true)}
          onValueChange={(v) => scrubbing && setCurrent(Math.round(v))}
          onSlidingComplete={(v) => {
            setScrubbing(false);
            speakFrom(Math.round(v));
          }}
          minimumTrackTintColor={palette.accent}
          maximumTrackTintColor={palette.border}
          thumbTintColor={palette.accent}
        />
        <IconBtn name="undo" label="From the beginning" onPress={restart} />
      </View>
    </View>
  );
}
