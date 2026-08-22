// Today: the only question a daily user has — what's due, and is the streak
// safe. A native mirror of the web screen, fed by the same endpoints.
import { useRouter } from "expo-router";
import React, { useCallback, useEffect, useState } from "react";
import { Pressable, RefreshControl, ScrollView, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { cached, dueCounts, heatCells, streakFrom } from "../../lib/data";
import { radius, space, target, usePalette } from "../../theme";
import { Button, Cap, CardBox, ErrorCard, IconBtn, NavRow, Pill, Skeleton, T, useToast } from "../../ui";

const NEEDS_YOU: Record<string, (job: any) => { line: string; action: string }> = {
  plan_ready: () => ({ line: "Plan ready", action: "Review plan" }),
  interrupted: () => ({ line: "Interrupted", action: "Resume" }),
  failed: (job) => ({ line: job.error || "Failed", action: "Retry" }),
};

export function StreakChip({ activity, now = new Date() }: { activity: any; now?: Date }) {
  const palette = usePalette();
  if (!activity) return null;
  const { streak, banked, studiedToday } = streakFrom(activity.days || [], now);
  if (streak === 0) return null;
  const atRisk = !studiedToday && now.getHours() >= 20;
  return (
    <View style={{
      flexDirection: "row", alignItems: "baseline", gap: 6,
      borderWidth: 3, borderColor: atRisk ? palette.borderStrong : palette.accent,
      borderRadius: radius.pill, paddingHorizontal: 14, paddingVertical: 6,
    }}>
      <T v="secondary" style={{ fontWeight: "600", color: atRisk ? palette.text2 : palette.accent, fontVariant: ["tabular-nums"] }}>
        Day {streak}
      </T>
      <Cap>
        {atRisk ? "expires 11:59 pm" : banked > 0 ? `· ${banked} rest day${banked > 1 ? "s" : ""}` : ""}
      </Cap>
    </View>
  );
}

function Heatmap({ days }: { days: any[] }) {
  const palette = usePalette();
  const heat = [palette.heat0, palette.heat1, palette.heat2, palette.heat3, palette.heat4];
  const cells = heatCells(days);
  const weeks: (typeof cells)[] = [];
  for (let w = 0; w < cells.length / 7; w++) weeks.push(cells.slice(w * 7, w * 7 + 7));
  return (
    <View style={{ flexDirection: "row", gap: 3 }}>
      {weeks.map((week, i) => (
        <View key={i} style={{ flex: 1, gap: 3 }}>
          {week.map((cell) => (
            <View key={cell.day} style={{
              width: "100%", aspectRatio: 1, borderRadius: 3,
              backgroundColor: heat[cell.level],
            }} />
          ))}
        </View>
      ))}
    </View>
  );
}

export default function Today() {
  const router = useRouter();
  const toast = useToast();
  const palette = usePalette();
  const [decks, setDecks] = useState<any[] | null>(null);
  const [counts, setCounts] = useState<Record<string, number | null>>({});
  const [activity, setActivity] = useState<any>(null);
  const [attention, setAttention] = useState<any[]>([]);
  const [writing, setWriting] = useState<Record<string, any>>({});
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const insets = useSafeAreaInsets();

  const load = useCallback(async () => {
    setError(null);
    try {
      const [deckList, jobs, act] = await Promise.all([
        cached("/api/decks", 30_000),
        cached("/api/jobs", 30_000),
        cached("/api/me/activity", 60_000),
      ]);
      setDecks(deckList.decks);
      setActivity(act);
      setAttention(jobs.jobs.filter((job: any) => NEEDS_YOU[job.state]));
      setWriting(Object.fromEntries(
        jobs.jobs.filter((j: any) => ["generating", "planning"].includes(j.state))
          .map((j: any) => [j.deck_id, j])
      ));
      setCounts(await dueCounts(deckList.decks));
    } catch (problem: any) {
      setError(problem.message);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const body = () => {
    if (error) return <ErrorCard message={error} onRetry={load} />;
    if (!decks) return (
      <>
        <Skeleton h={72} /><Skeleton h={150} r={radius.lg} />
        <Skeleton /><Skeleton /><Skeleton />
      </>
    );

    const totalDue = Object.values(counts).reduce((sum: number, n) => sum + (n || 0), 0);
    const decksWithDue = Object.values(counts).filter((n) => (n || 0) > 0).length;
    const weekReviews = (activity?.days || [])
      .filter((d: any) => Date.now() - new Date(d.day).getTime() < 7 * 86_400_000)
      .reduce((sum: number, d: any) => sum + d.reviews, 0);
    const firstRun = decks.length === 0;
    const sorted = [...decks].sort((a, b) => (counts[b.deck_id] || 0) - (counts[a.deck_id] || 0));

    return (
      <>
        <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
          <View>
            <T v="title">Today</T>
            <Cap>{new Date().toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" })}</Cap>
          </View>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 10 }}>
            <StreakChip activity={activity} />
            <IconBtn name="plus" label="Add a lecture"
              onPress={() => toast("Uploading a lecture lands on mobile next — use the web app for now.")} />
          </View>
        </View>

        {firstRun ? (
          <CardBox style={{ gap: space[3] }}>
            <T v="heading">How this works</T>
            <T v="secondary">
              Upload a lecture → approve the plan → read the lessons → review
              the cards → study a little every day. The app schedules what to
              see and when; your job is only to show up.
            </T>
            <Button title="Upload a lecture"
              onPress={() => toast("Uploading a lecture lands on mobile next — use the web app for now.")} />
          </CardBox>
        ) : (
          <CardBox style={{ padding: space[5] }}>
            {totalDue > 0 ? (
              <>
                <T v="statXl" style={{ fontVariant: ["tabular-nums"] }}>{totalDue}</T>
                <T v="secondary" style={{ marginTop: 2 }}>
                  cards due · {decksWithDue} deck{decksWithDue === 1 ? "" : "s"}
                </T>
                <Button title="Start reviewing" style={{ marginTop: space[4], minHeight: target.rating }}
                  onPress={() => router.push("/study/all")} />
              </>
            ) : (
              <>
                <T v="heading">All clear</T>
                <T v="secondary" style={{ marginTop: 2 }}>Nothing is due right now.</T>
                <Button title="Study ahead" kind="ghost" style={{ marginTop: space[4] }}
                  onPress={() => router.push("/study/all")} />
              </>
            )}
          </CardBox>
        )}

        {attention.map((job) => {
          const note = NEEDS_YOU[job.state](job);
          return (
            <Pressable key={job.job_id}
              onPress={() => toast("Finish this on the web for now — job screens land on mobile next.")}
              style={{
                flexDirection: "row", alignItems: "center", gap: space[3],
                backgroundColor: palette.accentSoft, borderRadius: radius.md,
                paddingHorizontal: 14, paddingVertical: 12, minHeight: target.min,
              }}>
              <View style={{ flex: 1 }}>
                <T v="secondary" style={{ fontWeight: "600", color: palette.text }}>
                  {job.deck_name || job.source_filename}
                </T>
                <Cap>{note.line}</Cap>
              </View>
              <T v="secondary" style={{ fontWeight: "600", color: palette.accent }}>{note.action}</T>
            </Pressable>
          );
        })}

        {activity && activity.days?.length > 0 && (
          <CardBox style={{ gap: space[3] }}>
            <View style={{ flexDirection: "row", alignItems: "baseline", justifyContent: "space-between" }}>
              <T v="heading">Activity</T>
              <Cap>{weekReviews} reviews this week</Cap>
            </View>
            <Heatmap days={activity.days} />
          </CardBox>
        )}

        {sorted.length > 0 && (
          <View style={{ gap: space[2] }}>
            {sorted.map((deck) => (
              <NavRow key={deck.deck_id} onPress={() => router.push(`/deck/${deck.deck_id}`)}
                right={
                  writing[deck.deck_id] ? (
                    <Pill text="writing…" accent />
                  ) : (counts[deck.deck_id] || 0) > 0 ? (
                    <Pill text={`${counts[deck.deck_id]} due`} accent />
                  ) : null
                }>
                <T v="body" style={{ fontWeight: "600" }}>{deck.name}</T>
                <Cap>
                  {deck.card_count} cards
                  {deck.shared_with_me ? ` · from ${deck.owner_name}` : ""}
                </Cap>
              </NavRow>
            ))}
          </View>
        )}
      </>
    );
  };

  return (
    <ScrollView
      style={{ flex: 1, backgroundColor: palette.bg }}
      contentContainerStyle={{ padding: space[3], gap: space[3], paddingTop: insets.top + space[2], paddingBottom: space[6] }}
      refreshControl={
        <RefreshControl refreshing={refreshing} onRefresh={async () => {
          setRefreshing(true);
          const { dropCache } = await import("../../lib/data");
          dropCache("/api");
          await load();
          setRefreshing(false);
        }} />
      }
    >
      {body()}
    </ScrollView>
  );
}
