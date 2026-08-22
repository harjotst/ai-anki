// The lesson reader, phone side. Reading comes before drilling; read state
// persists on the device (same key shape as the web's localStorage) so
// reopening resumes where the person left off.
import AsyncStorage from "@react-native-async-storage/async-storage";
import { useLocalSearchParams, useRouter } from "expo-router";
import React, { useCallback, useEffect, useState } from "react";
import { Pressable, ScrollView, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { api } from "../../lib/session";
import { radius, space, target, usePalette } from "../../theme";
import { Cap, CardBox, Button, ErrorCard, Icon, IconBtn, Sheet, Skeleton, T, useToast } from "../../ui";

const readKey = (jobId: string) => `ai_anki_read:${jobId}`;
const loadRead = async (jobId: string) =>
  new Set<string>(JSON.parse((await AsyncStorage.getItem(readKey(jobId))) || "[]"));

// The web's 17px/1.6 reading measure; T's body variant is a step smaller.
const prose = { fontSize: 17, lineHeight: 27 };

export default function Lessons() {
  const { jobId } = useLocalSearchParams<{ jobId: string }>();
  const router = useRouter();
  const toast = useToast();
  const palette = usePalette();
  const insets = useSafeAreaInsets();

  const [lessons, setLessons] = useState<any[] | null>(null);
  const [jobState, setJobState] = useState<string | null>(null);
  const [read, setRead] = useState<Set<string>>(new Set());
  const [open, setOpen] = useState(0);
  const [sheet, setSheet] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [body, job, seen] = await Promise.all([
        api(`/api/jobs/${jobId}/lessons`),
        api(`/api/jobs/${jobId}`),
        loadRead(jobId!),
      ]);
      setLessons(body.lessons);
      setJobState(job.state);
      setRead(seen);
      // Resume where they left off: the first unread lesson.
      const firstUnread = body.lessons.findIndex((l: any) => !seen.has(l.topic_id));
      if (firstUnread > 0) setOpen((current) => (current === 0 ? firstUnread : current));
    } catch (problem: any) {
      // An error is a retryable state — never a silent empty list.
      setError(problem.message);
    }
  }, [jobId]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (jobState !== "generating") return undefined;
    const timer = setInterval(load, 4000);
    return () => clearInterval(timer);
  }, [jobState, load]);

  // Server-confirmed zero lessons: the web goes straight to the job's cards,
  // a screen that does not exist on mobile yet.
  const emptyDone = lessons !== null && lessons.length === 0 && jobState !== "generating";
  useEffect(() => {
    if (!emptyDone) return;
    toast("Finish this on the web for now — job screens land on mobile next.");
    router.back();
  }, [emptyDone, toast, router]);

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
          <IconBtn name="chevL" label="Back" onPress={() => router.back()} />
        </View>
        <View style={{ padding: space[3], paddingTop: 60, gap: space[2] }}>
          <T v="heading">The first lesson is being written</T>
          <T v="secondary">You can start reading the moment it lands.</T>
        </View>
      </View>
    );
  }

  const lesson = lessons[Math.min(open, lessons.length - 1)];
  const last = open >= lessons.length - 1 && jobState !== "generating";

  const advance = () => {
    markRead(lesson.topic_id);
    if (open < lessons.length - 1) setOpen(open + 1);
    // The web continues to the job's card review; that screen is web-only.
    else toast("Finish this on the web for now — job screens land on mobile next.");
  };

  return (
    <View style={{ flex: 1, backgroundColor: palette.bg, paddingTop: insets.top, paddingBottom: insets.bottom + space[2] }}>
      <View style={{ flexDirection: "row", alignItems: "center", paddingHorizontal: space[2] }}>
        <IconBtn name="chevL" label="Back" onPress={() => router.back()} />
        <View style={{ flex: 1, alignItems: "center" }}>
          <Pressable onPress={() => setSheet(true)}
            style={({ pressed }) => ({
              flexDirection: "row", alignItems: "center", gap: 6, minHeight: target.min,
              backgroundColor: pressed ? palette.border : palette.sunken,
              borderRadius: radius.pill, paddingHorizontal: 14,
            })}>
            <Cap color={palette.text} style={{ fontWeight: "600", fontVariant: ["tabular-nums"] }}>
              Topic {open + 1} of {lessons.length}{jobState === "generating" ? "+" : ""}
            </Cap>
            <Icon name="chevD" size={14} color={palette.muted} />
          </Pressable>
        </View>
        <View style={{ width: target.min }} />
      </View>

      <View style={{ paddingHorizontal: space[3] }}>
        <View style={{ height: 3, borderRadius: 2, backgroundColor: palette.sunken }}>
          <View style={{
            height: 3, borderRadius: 2, backgroundColor: palette.accent,
            width: `${((open + 1) / lessons.length) * 100}%`,
          }} />
        </View>
      </View>

      <ScrollView style={{ flex: 1 }} contentContainerStyle={{ padding: space[3], paddingBottom: space[5], gap: space[3] }}>
        <T v="title">{lesson.deck_path.split("::").pop()}</T>
        <T style={{ ...prose, fontStyle: "italic" }}>{lesson.in_one_line}</T>

        <View>
          <T v="heading" style={{ marginBottom: 6 }}>Why it matters</T>
          <T style={prose}>{lesson.why_it_matters}</T>
        </View>

        {lesson.sections.map((section: any) => (
          <View key={section.heading}>
            <T v="heading" style={{ marginBottom: 6 }}>{section.heading}</T>
            {section.builds_on && (
              <Cap style={{ fontStyle: "italic", marginBottom: 6 }}>
                Builds on: {section.builds_on}
              </Cap>
            )}
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

        {lesson.misconceptions?.length > 0 && (
          <View style={{ gap: space[2] }}>
            <T v="heading">What people get wrong</T>
            {lesson.misconceptions.map((myth: any) => (
              <View key={myth.belief} style={{
                borderLeftWidth: 3, borderLeftColor: palette.accent,
                paddingLeft: 14, paddingVertical: 4, gap: 4,
              }}>
                <T style={{ ...prose, fontWeight: "600" }}>{`“${myth.belief}”`}</T>
                <T v="secondary" style={{ fontSize: 15, lineHeight: 23 }}>{myth.why_it_is_wrong}</T>
              </View>
            ))}
          </View>
        )}

        {lesson.check_yourself?.length > 0 && (
          <View>
            <T v="heading" style={{ marginBottom: 6 }}>Check yourself</T>
            <View style={{ gap: 6 }}>
              {lesson.check_yourself.map((question: string) => (
                <View key={question} style={{ flexDirection: "row", gap: space[1] }}>
                  <T style={prose}>{"•"}</T>
                  <T style={[prose, { flex: 1 }]}>{question}</T>
                </View>
              ))}
            </View>
          </View>
        )}

        {last && (
          <CardBox style={{ padding: 20, alignItems: "center" }}>
            <T v="heading">That was the last topic</T>
            <T v="secondary" style={{ marginTop: 4 }}>The cards are ready to look over.</T>
          </CardBox>
        )}
      </ScrollView>

      <View style={{ flexDirection: "row", gap: space[1], paddingHorizontal: space[3], paddingTop: space[2] }}>
        <Button title="Previous" kind="ghost" style={{ flex: 1 }} disabled={open === 0}
          onPress={() => setOpen(open - 1)} />
        <Button title={last ? "Review the cards" : "Mark read · Next"} style={{ flex: 1.6 }}
          onPress={advance} />
      </View>

      {sheet && (
        <Sheet onClose={() => setSheet(false)}>
          <T v="heading">Topics</T>
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
