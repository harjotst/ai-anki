// A single topic's lesson, reached from deck detail — the phone side of the
// web's DeckLesson. The lesson lives on whichever job built this deck, so
// the deck's jobs are tried in order until one can teach the topic. The
// reading itself is LessonSteps: one idea per screen, finishing goes back
// to the deck.
import { useLocalSearchParams } from "expo-router";
import React, { useCallback, useEffect, useState } from "react";
import { View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { cached } from "../../../../lib/data";
import { useGoBack } from "../../../../lib/nav";
import { api } from "../../../../lib/session";
import { space, usePalette } from "../../../../theme";
import { ErrorCard, Skeleton } from "../../../../ui";
import { LessonSteps } from "../../../../ui/lesson-steps";

export default function DeckLesson() {
  const { id, topicId } = useLocalSearchParams<{ id: string; topicId: string }>();
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
    <LessonSteps
      lesson={lesson}
      title={lesson.deck_path.split("::").pop()}
      footerLabel="Back to the deck"
      onFinished={() => goBack()}
      onExit={() => goBack()}
    />
  );
}
