// A single topic's lesson, reached from deck detail — the phone side of the
// web's DeckLesson. The lesson lives on whichever job built this deck, so
// the deck's jobs are tried in order until one can teach the topic.
import { useLocalSearchParams, useRouter } from "expo-router";
import { useGoBack } from "../../../../lib/nav";
import React, { useCallback, useEffect, useState } from "react";
import { ScrollView, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { cached } from "../../../../lib/data";
import { api } from "../../../../lib/session";
import { radius, space, target, usePalette } from "../../../../theme";
import { Cap, ErrorCard, IconBtn, Skeleton, T } from "../../../../ui";

// The web's 17px/1.6 reading measure; T's body variant is a step smaller.
const prose = { fontSize: 17, lineHeight: 27 };

export default function DeckLesson() {
  const { id, topicId } = useLocalSearchParams<{ id: string; topicId: string }>();
  const router = useRouter();
  const goBack = useGoBack();
  const palette = usePalette();
  const insets = useSafeAreaInsets();

  const [lesson, setLesson] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const { jobs } = await cached("/api/jobs", 60_000);
      const candidates = jobs.filter((job: any) => job.deck_id === id);
      for (const job of candidates) {
        try {
          setLesson(await api(`/api/jobs/${job.job_id}/topics/${topicId}/lesson`));
          return;
        } catch {
          /* try the next job that built this deck */
        }
      }
      throw new Error("This topic has not been taught yet.");
    } catch (problem: any) {
      setError(problem.message);
    }
  }, [id, topicId]);

  useEffect(() => { load(); }, [load]);

  if (error) return (
    <View style={{ flex: 1, backgroundColor: palette.bg, padding: space[3], paddingTop: insets.top + space[3] }}>
      <ErrorCard message={error} onRetry={load} />
    </View>
  );
  if (!lesson) return (
    <View style={{ flex: 1, backgroundColor: palette.bg, padding: space[3], paddingTop: insets.top + space[3] }}>
      <Skeleton h={300} />
    </View>
  );

  return (
    <View style={{ flex: 1, backgroundColor: palette.bg, paddingTop: insets.top }}>
      <View style={{ flexDirection: "row", alignItems: "center", paddingHorizontal: space[2] }}>
        <IconBtn name="chevL" label="Back" onPress={() => goBack()} />
        <Cap style={{ flex: 1, textAlign: "center" }}>{lesson.deck_path.split("::").pop()}</Cap>
        <View style={{ width: target.min }} />
      </View>

      <ScrollView
        style={{ flex: 1 }}
        contentContainerStyle={{
          padding: space[3], paddingTop: space[0], gap: space[3],
          paddingBottom: insets.bottom + space[6],
        }}
      >
        <T style={{ ...prose, fontStyle: "italic" }}>{lesson.in_one_line}</T>
        <T style={prose}>{lesson.why_it_matters}</T>

        {lesson.sections.map((section: any) => (
          <View key={section.heading}>
            <T v="heading" style={{ marginBottom: 6 }}>{section.heading}</T>
            <T style={prose}>{section.body}</T>
          </View>
        ))}

        {lesson.worked_example && (
          <View style={{
            backgroundColor: palette.sunken, borderRadius: radius.md,
            paddingHorizontal: space[3], paddingVertical: 14, gap: 6,
          }}>
            <Cap style={{ letterSpacing: 0.7 }}>WORKED EXAMPLE</Cap>
            <T style={{ ...prose, fontWeight: "600" }}>{lesson.worked_example.problem}</T>
            <T style={prose}>{lesson.worked_example.walkthrough}</T>
          </View>
        )}

        {lesson.misconceptions?.map((myth: any) => (
          <View key={myth.belief} style={{
            borderLeftWidth: 3, borderLeftColor: palette.accent,
            paddingLeft: 14, paddingVertical: 4, gap: 4,
          }}>
            <T style={{ ...prose, fontWeight: "600" }}>{`“${myth.belief}”`}</T>
            <T v="secondary" style={{ fontSize: 15, lineHeight: 23 }}>{myth.why_it_is_wrong}</T>
          </View>
        ))}
      </ScrollView>
    </View>
  );
}
