// Today: the only question a daily user has — what's due, and is the streak
// safe. A native mirror of the web screen, fed by the same endpoints.
import { type Href, useFocusEffect, useRouter } from "expo-router";
import React, { useCallback, useEffect, useState } from "react";
import { Pressable, RefreshControl, ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { cached, dueCounts, localDay, streakFrom } from "../../lib/data";
import { deckStillForming, LIVE_STATES, useLiveJobs } from "../../lib/live-jobs";
import { radius, space, target, usePalette } from "../../theme";
import { Button, Cap, CardBox, ErrorCard, IconBtn, NavRow, Pill, Skeleton, T } from "../../ui";
import { JobProgressCard } from "../../ui/job-progress";
import { Mascot } from "../../ui/mascot";

// The /job screens land in this same change set; the generated route types
// refresh only when the dev server runs, hence the Href casts below.
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

// A month of activity at phone size: four Monday-aligned weeks ending today.
// 84 micro-cells read as noise on a phone; 28 large ones read as a calendar.
function MonthCalendar({ days }: { days: any[] }) {
  const palette = usePalette();
  const byDay = Object.fromEntries(days.map((d: any) => [d.day, d.reviews]));
  const now = new Date();
  const year = now.getFullYear();
  const month = now.getMonth();
  const todayKey = localDay(now);
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  // Monday-first column of the 1st, then the month laid out week by week —
  // the same shape as the calendar on the wall, because that is the shape
  // people already know how to read.
  const lead = (new Date(year, month, 1).getDay() + 6) % 7;
  const cells: (number | null)[] = [
    ...Array(lead).fill(null),
    ...Array.from({ length: daysInMonth }, (_, i) => i + 1),
  ];
  while (cells.length % 7) cells.push(null);
  const weeks: (number | null)[][] = [];
  for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7));

  const keyOf = (day: number) =>
    `${year}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;

  return (
    <View style={{ gap: 6 }}>
      <View style={{ flexDirection: "row", gap: 5 }}>
        {["M", "T", "W", "T", "F", "S", "S"].map((initial, i) => (
          <Cap key={i} style={{ flex: 1, textAlign: "center" }}>{initial}</Cap>
        ))}
      </View>
      {weeks.map((week, r) => (
        <View key={r} style={{ flexDirection: "row", gap: 5 }}>
          {week.map((day, c) => {
            if (day === null) return <View key={`pad${c}`} style={{ flex: 1, aspectRatio: 1 }} />;
            const key = keyOf(day);
            const reviews = byDay[key] || 0;
            // Two shades, not five: studied, and studied a lot. A ramp nobody
            // can decode is decoration; two states are legible at a glance.
            const big = reviews >= 15;
            const some = reviews > 0;
            const isToday = key === todayKey;
            return (
              <View key={key} style={{
                flex: 1, aspectRatio: 1, borderRadius: radius.sm,
                alignItems: "center", justifyContent: "center",
                backgroundColor: big ? palette.accent : some ? palette.accentSoft : undefined,
                borderWidth: isToday ? 2 : 0, borderColor: palette.accent,
              }}>
                <Text style={{
                  fontSize: 13, fontVariant: ["tabular-nums"],
                  fontWeight: isToday || big ? "600" : "400",
                  color: big ? palette.onAccent : some ? palette.accent : palette.text2,
                }}>
                  {day}
                </Text>
              </View>
            );
          })}
        </View>
      ))}
      <Cap style={{ textAlign: "center" }}>tinted · studied      solid · 15+ reviews</Cap>
    </View>
  );
}

export default function Today() {
  const router = useRouter();
  const palette = usePalette();
  const [decks, setDecks] = useState<any[] | null>(null);
  const [counts, setCounts] = useState<Record<string, number | null>>({});
  // Decks land a beat before due counts do; until the first counts resolve,
  // "nothing due" would be a guess, and a wrong one flashes "All clear".
  const [countsReady, setCountsReady] = useState(false);
  const [activity, setActivity] = useState<any>(null);
  const [attention, setAttention] = useState<any[]>([]);
  const [writing, setWriting] = useState<Record<string, any>>({});
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const insets = useSafeAreaInsets();
  // The live pulse: fresh job states every few seconds while anything runs,
  // and a bumped `pulse` whenever a state changed — the moment a plan turns
  // ready this screen re-renders, without waiting for a refocus.
  const { jobs: liveJobs, pulse } = useLiveJobs();

  const load = useCallback(async () => {
    setError(null);
    try {
      const [deckList, jobs, act] = await Promise.all([
        cached("/api/decks", 30_000),
        cached("/api/jobs", 30_000),
        cached(`/api/me/activity?tz_offset=${-new Date().getTimezoneOffset()}`, 60_000),
      ]);
      setDecks(deckList.decks);
      setActivity(act);
      setAttention(jobs.jobs.filter((job: any) => NEEDS_YOU[job.state]));
      setWriting(Object.fromEntries(
        jobs.jobs.filter((j: any) => ["generating", "planning"].includes(j.state))
          .map((j: any) => [j.deck_id, j])
      ));
      setCounts(await dueCounts(deckList.decks));
      setCountsReady(true);
    } catch (problem: any) {
      setError(problem.message);
    }
  }, []);

  // On focus, not just mount: coming back from a study session (which drops
  // the cache) or a job screen must show the new numbers without a reload.
  useFocusEffect(useCallback(() => { load(); }, [load]));

  // A job changed state while we watched: decks and counts are stale too.
  useEffect(() => { if (pulse) load(); }, [pulse, load]);

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
    const { streak } = streakFrom(activity?.days || []);
    // Live states beat the 30s cache the moment the poll has answered once.
    const jobsNow = liveJobs ?? [...attention, ...Object.values(writing)];
    const attentionNow = jobsNow.filter((job: any) => NEEDS_YOU[job.state]);
    const buildingNow = jobsNow.filter((job: any) => LIVE_STATES.includes(job.state));
    const openJobs = jobsNow.filter(
      (job: any) => job.state !== "complete" && job.state !== "cancelled"
    );
    const firstRun = decks.length === 0 && openJobs.length === 0;
    const sorted = [...decks]
      // A deck still being made is the job's business: its card shows above,
      // says what is happening, and opens the run — never an empty shell.
      .filter((deck) => !deckStillForming(deck, jobsNow))
      .sort((a, b) => (counts[b.deck_id] || 0) - (counts[a.deck_id] || 0));

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
              onPress={() => router.push("/job/new" as Href)} />
          </View>
        </View>

        {firstRun ? (
          <CardBox style={{ gap: space[3], alignItems: "center" }}>
            <Mascot size={120} />
            <T v="heading">How this works</T>
            <T v="secondary">
              Upload a lecture → approve the plan → read the lessons → review
              the cards → study a little every day. The app schedules what to
              see and when; your job is only to show up.
            </T>
            <Button title="Upload a lecture"
              onPress={() => router.push("/job/new" as Href)} />
          </CardBox>
        ) : !countsReady ? (
          <Skeleton h={150} r={radius.lg} />
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

        {attentionNow.map((job) => (
          <JobProgressCard key={job.job_id} job={job} />
        ))}
        {buildingNow.map((job) => (
          <JobProgressCard key={job.job_id} job={job} />
        ))}

        {activity && activity.days?.length > 0 && (
          <CardBox style={{ gap: space[3] }}>
            <View style={{ flexDirection: "row", alignItems: "baseline", justifyContent: "space-between" }}>
              <T v="heading">{new Date().toLocaleDateString(undefined, { month: "long" })}</T>
              <Cap>{weekReviews} reviews this week</Cap>
            </View>
            <MonthCalendar days={activity.days} />
            {streak > 0 && (
              <Cap>{streak} day{streak === 1 ? "" : "s"} in a row</Cap>
            )}
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
