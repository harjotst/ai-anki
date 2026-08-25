// The lesson reader, phone side. Reading comes before drilling; read state
// persists on the device (same key shape as the web's localStorage) so
// reopening resumes where the person left off. Each topic is walked one
// step at a time by LessonSteps — finishing a topic marks it read and
// rolls straight into the next topic's first step.
import AsyncStorage from "@react-native-async-storage/async-storage";
import { type Href, useLocalSearchParams, useRouter } from "expo-router";
import React, { useCallback, useEffect, useRef, useState } from "react";
import { Pressable, ScrollView, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useGoBack } from "../../lib/nav";
import { api } from "../../lib/session";
import { radius, space, target, usePalette } from "../../theme";
import { Cap, ErrorCard, Icon, IconBtn, Skeleton, Sheet, T, useToast } from "../../ui";
import { LessonSteps } from "../../ui/lesson-steps";

const readKey = (jobId: string) => `ai_anki_read:${jobId}`;
const loadRead = async (jobId: string) =>
  new Set<string>(JSON.parse((await AsyncStorage.getItem(readKey(jobId))) || "[]"));

export default function Lessons() {
  const { jobId } = useLocalSearchParams<{ jobId: string }>();
  const router = useRouter();
  const goBack = useGoBack();
  const toast = useToast();
  const palette = usePalette();
  const insets = useSafeAreaInsets();

  const [lessons, setLessons] = useState<any[] | null>(null);
  const [jobState, setJobState] = useState<string | null>(null);
  const [read, setRead] = useState<Set<string>>(new Set());
  const [open, setOpen] = useState(0);
  const [sheet, setSheet] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Once anything has loaded, a flaky background poll must not replace the
  // whole reader with an error card.
  const loadedOnce = useRef(false);
  const resumed = useRef(false);

  const load = useCallback(async () => {
    try {
      const [body, job, seen] = await Promise.all([
        api(`/api/jobs/${jobId}/lessons`),
        api(`/api/jobs/${jobId}`),
        loadRead(jobId!),
      ]);
      setLessons(body.lessons);
      setJobState(job.state);
      setRead(seen);
      setError(null);
      loadedOnce.current = true;
      // Resume where they left off: the first unread lesson — once per
      // visit, or every poll would yank a person who navigated back to a
      // topic they had already read.
      if (!resumed.current && body.lessons.length) {
        resumed.current = true;
        const firstUnread = body.lessons.findIndex((l: any) => !seen.has(l.topic_id));
        if (firstUnread > 0) setOpen((current) => (current === 0 ? firstUnread : current));
      }
    } catch (problem: any) {
      // An error is a retryable state — never a silent empty list. But
      // background polls fail quietly; the next tick retries.
      if (!loadedOnce.current) setError(problem.message);
    }
  }, [jobId]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (jobState !== "generating") return undefined;
    const timer = setInterval(load, 4000);
    return () => clearInterval(timer);
  }, [jobState, load]);

  // Server-confirmed zero lessons: nothing to read, straight to the cards,
  // exactly as the web does.
  const emptyDone = lessons !== null && lessons.length === 0 && jobState !== "generating";
  useEffect(() => {
    if (!emptyDone) return;
    router.replace(`/job/${jobId}/cards` as Href);
  }, [emptyDone, router, jobId]);

  const markRead = useCallback((topicId: string) => {
    setRead((current) => {
      if (current.has(topicId)) return current;
      const next = new Set(current);
      next.add(topicId);
      void AsyncStorage.setItem(readKey(jobId!), JSON.stringify([...next]));
      return next;
    });
  }, [jobId]);

  if (error) return (
    <View style={{ flex: 1, backgroundColor: palette.bg, padding: space[3], paddingTop: insets.top + space[3] }}>
      <ErrorCard message={error} onRetry={load} />
    </View>
  );
  if (!lessons) return (
    <View style={{ flex: 1, backgroundColor: palette.bg, padding: space[3], paddingTop: insets.top + space[3], gap: space[2] }}>
      <Skeleton h={40} />
      <Skeleton h={300} />
    </View>
  );

  if (!lessons.length) {
    if (jobState !== "generating") return null; // the effect above bounces back
    return (
      <View style={{ flex: 1, backgroundColor: palette.bg, paddingTop: insets.top }}>
        <View style={{ flexDirection: "row", alignItems: "center", paddingHorizontal: space[2] }}>
          <IconBtn name="chevL" label="Back" onPress={() => goBack()} />
        </View>
        <View style={{ padding: space[3], paddingTop: 60, gap: space[2] }}>
          <T v="heading">The first lesson is being written</T>
          <T v="secondary">You can start reading the moment it lands.</T>
        </View>
      </View>
    );
  }

  const lesson = lessons[Math.min(open, lessons.length - 1)];
  const lastTopic = open >= lessons.length - 1;

  const finishTopic = () => {
    markRead(lesson.topic_id);
    if (!lastTopic) setOpen(open + 1);
    // Href cast: the generated route types refresh only when the dev server
    // runs, and the job screens land in this same change set.
    else router.push(`/job/${jobId}/cards` as Href);
  };

  return (
    <View style={{ flex: 1, backgroundColor: palette.bg }}>
      <LessonSteps
        /* keyed by topic: a new topic always begins on its first step */
        key={lesson.topic_id}
        lesson={lesson}
        title={lesson.deck_path.split("::").pop()}
        footerLabel={lastTopic ? "On to the cards" : "Next topic"}
        onFinished={finishTopic}
        onExit={() => goBack()}
        headerRight={<IconBtn name="decks" label="Topics" onPress={() => setSheet(true)} />}
      />

      {sheet && (
        <Sheet onClose={() => setSheet(false)}>
          <T v="heading">
            Topics · {open + 1} of {lessons.length}{jobState === "generating" ? "+" : ""}
          </T>
          <ScrollView style={{ flexShrink: 1 }} contentContainerStyle={{ gap: space[1] }}>
            {lessons.map((entry: any, index: number) => (
              <Pressable key={entry.topic_id}
                onPress={() => { setOpen(index); setSheet(false); }}
                style={({ pressed }) => ({
                  minHeight: target.min, borderRadius: radius.md, borderWidth: 1,
                  borderColor: index === open ? palette.accent : palette.borderStrong,
                  backgroundColor: pressed ? palette.sunken : "transparent",
                  flexDirection: "row", alignItems: "center", justifyContent: "space-between",
                  gap: space[2], paddingHorizontal: space[3],
                })}>
                <T style={{ fontWeight: "600", flex: 1 }}>{entry.deck_path.split("::").pop()}</T>
                {read.has(entry.topic_id) && <Icon name="check" size={16} color={palette.accent} />}
              </Pressable>
            ))}
          </ScrollView>
          {jobState === "generating" && <Cap>writing the next topic…</Cap>}
        </Sheet>
      )}
    </View>
  );
}
