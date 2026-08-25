// One job, watched from upload to deck: plan review, generation, and the
// broken branches (interrupted, failed) that used to dead-end. The phone
// has no EventSource, so this polls the job the way the web's fallback does.
import { useLocalSearchParams, useRouter } from "expo-router";
import { useGoBack } from "../../../lib/nav";
import React, { useCallback, useEffect, useRef, useState } from "react";
import { Pressable, ScrollView, TextInput, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { dropCache } from "../../../lib/data";
import { api } from "../../../lib/session";
import { radius, space, target, usePalette } from "../../../theme";
import { Button, Cap, CardBox, ErrorCard, IconBtn, Seg, Skeleton, T } from "../../../ui";

export default function JobRun() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const jobId = String(id);
  const router = useRouter();
  const goBack = useGoBack();
  const [job, setJob] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [planError, setPlanError] = useState<string | null>(null);
  const planFired = useRef(false);

  const refresh = useCallback(async () => {
    try {
      setJob(await api(`/api/jobs/${jobId}`));
      setError(null);
    } catch (problem: any) {
      if (String(problem.message).includes("not found")) router.replace("/");
      else setError(problem.message);
    }
  }, [jobId, router]);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 2000);
    return () => clearInterval(timer);
  }, [refresh]);

  // An uploaded job sits still until something starts it; the client joins
  // the two calls, exactly once.
  useEffect(() => {
    if (!job || job.state !== "uploaded" || planFired.current || planError) return;
    planFired.current = true;
    api(`/api/jobs/${jobId}/plan`, { method: "POST" }).then(refresh).catch((p) => {
      // Re-arm, or Retry would show an eternal "Reading your material". The
      // standing planError keeps the 2s poll from auto-refiring a bad plan.
      planFired.current = false;
      setPlanError(p.message);
    });
  }, [job, jobId, refresh, planError]);

  useEffect(() => {
    if (job?.state === "complete") router.replace(`/lessons/${jobId}`);
  }, [job, jobId, router]);

  // A failure before anything has loaded owns the screen. Once content is
  // up, a failed background poll must NOT unmount it — plan edits live
  // there — so it becomes a quiet retry row above the last-good render.
  if (error && !job) return <Frame title="Upload"><ErrorCard message={error} onRetry={refresh} /></Frame>;
  if (!job) return <Frame title=""><Skeleton h={120} /></Frame>;

  if (planError)
    return (
      <Frame title={job.source_filename || "Upload"}>
        <ErrorCard message={planError} onRetry={() => { setPlanError(null); refresh(); }} />
      </Frame>
    );

  const notice = error ? <RetryRow message={error} onRetry={refresh} /> : null;

  if (["uploaded", "planning"].includes(job.state))
    return (
      <Frame title={job.source_filename || "Planning"} notice={notice}>
        <CardBox style={{ padding: space[4], gap: space[1] }}>
          <T v="heading">Reading your material</T>
          <T v="secondary">
            Breaking it into topics and judging how much each is worth. You can
            leave — this keeps running.
          </T>
          <View style={{ marginTop: space[1] }}>
            <Hairline fraction={0.3} />
          </View>
        </CardBox>
      </Frame>
    );

  if (job.state === "plan_ready" && job.plan)
    return <PlanReview job={job} onApproved={refresh} notice={notice} />;

  if (job.state === "generating" || job.state === "reviewing")
    return <Generating job={job} notice={notice} />;

  if (job.state === "interrupted")
    return (
      <Frame title={job.source_filename || "Interrupted"} notice={notice}>
        <CardBox style={{ padding: space[4], gap: space[2] }}>
          <T v="heading">Interrupted</T>
          <T v="secondary">
            The machine restarted part-way through. Everything already written is
            safe; resuming only runs what is left.
          </T>
          <Button title="Resume"
            onPress={() => api(`/api/jobs/${jobId}/${job.plan ? "generate" : "plan"}`, { method: "POST" })
              .then(refresh)
              .catch((p) => setError(p.message))} />
        </CardBox>
      </Frame>
    );

  if (job.state === "failed")
    return (
      <Frame title={job.source_filename || "Failed"} notice={notice}>
        <ErrorCard
          message={job.error || "This upload failed."}
          onRetry={() =>
            api(`/api/jobs/${jobId}/clear`, { method: "POST" })
              .catch(() => {})
              .then(() => api(`/api/jobs/${jobId}/${job.plan ? "generate" : "plan"}`, { method: "POST" }))
              .then(refresh)
              .catch((p) => setError(p.message))
          }
        />
      </Frame>
    );

  if (job.state === "dead")
    return (
      <Frame title={job.source_filename || "Stopped"} notice={notice}>
        <CardBox style={{ padding: space[4], gap: space[2] }}>
          <T v="heading">Stopped</T>
          <T v="secondary">
            This failed several times in a row, so it stopped trying on its
            own. Everything already written is safe; starting again runs only
            what is left.
          </T>
          <Button title="Start again"
            onPress={() =>
              // Clearing is the required first step for a dead job — it must
              // land before the resume call, so its failure is not swallowed.
              api(`/api/jobs/${jobId}/clear`, { method: "POST" })
                .then(() => api(`/api/jobs/${jobId}/${job.plan ? "generate" : "plan"}`, { method: "POST" }))
                .then(refresh)
                .catch((p) => setError(p.message))} />
        </CardBox>
      </Frame>
    );

  return <Frame title="" notice={notice}><Skeleton h={120} /></Frame>;
}

// The stack-screen shell: back chevron, centered caption title, and an
// optional bar pinned below the scroll, above the home-indicator inset —
// the native seat of the web's .bulkbar.
function Frame({ title, caption, notice, footer, children }: {
  title: string; caption?: string; notice?: React.ReactNode;
  footer?: React.ReactNode; children: React.ReactNode;
}) {
  const router = useRouter();
  const goBack = useGoBack();
  const palette = usePalette();
  const insets = useSafeAreaInsets();
  return (
    <View style={{ flex: 1, backgroundColor: palette.bg, paddingTop: insets.top }}>
      <View style={{ flexDirection: "row", alignItems: "center", paddingHorizontal: space[2] }}>
        <IconBtn name="chevL" label="Back" onPress={() => goBack()} />
        <View style={{ flex: 1, alignItems: "center" }}>
          <Cap style={{ textAlign: "center" }}>{title}</Cap>
          {caption ? <Cap color={palette.muted} style={{ textAlign: "center" }}>{caption}</Cap> : null}
        </View>
        <View style={{ width: target.min }} />
      </View>
      <ScrollView
        style={{ flex: 1 }}
        keyboardShouldPersistTaps="handled"
        contentContainerStyle={{
          padding: space[3], gap: space[3],
          paddingBottom: footer ? space[4] : insets.bottom + space[4],
        }}
      >
        {notice}
        {children}
      </ScrollView>
      {footer}
    </View>
  );
}

// A background poll failed after content had loaded: keep what the user is
// looking at and offer a quiet retry instead of unmounting the screen.
function RetryRow({ message, onRetry }: { message: string; onRetry: () => void }) {
  const palette = usePalette();
  return (
    <View style={{
      flexDirection: "row", alignItems: "center", gap: space[2],
      backgroundColor: palette.sunken, borderRadius: radius.md,
      paddingHorizontal: 14, paddingVertical: space[1],
    }}>
      <T v="caption" numberOfLines={2} style={{ flex: 1 }}>{message}</T>
      <Pressable onPress={onRetry}
        style={{ minHeight: target.min, justifyContent: "center", paddingHorizontal: space[1] }}>
        <T v="secondary" color={palette.accent} style={{ fontWeight: "600" }}>Retry</T>
      </Pressable>
    </View>
  );
}

// The web's .hairline: a 3px track with an accent fill.
function Hairline({ fraction }: { fraction: number }) {
  const palette = usePalette();
  return (
    <View style={{ height: 3, borderRadius: 2, backgroundColor: palette.sunken, overflow: "hidden" }}>
      <View style={{
        height: 3, borderRadius: 2, backgroundColor: palette.accent,
        width: `${fraction * 100}%`,
      }} />
    </View>
  );
}

// --- plan review -----------------------------------------------------------

const slug = (text: string) =>
  text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 40) || "topic";

function PlanReview({ job, onApproved, notice }: {
  job: any; onApproved: () => void; notice?: React.ReactNode;
}) {
  const palette = usePalette();
  const insets = useSafeAreaInsets();
  const [topics, setTopics] = useState<any[]>(job.plan.topics.map((t: any) => ({ ...t, dropped: false })));
  const [estimate, setEstimate] = useState<any>(undefined); // undefined loading, null failed
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api(`/api/jobs/${job.job_id}/estimate`).then(setEstimate).catch(() => setEstimate(null));
  }, [job.job_id]);

  const edit = (index: number, patch: any) =>
    setTopics((current) => current.map((t, i) => (i === index ? { ...t, ...patch } : t)));

  const kept = topics.filter((t) => !t.dropped);
  const totalCards = kept.reduce((sum, t) => sum + Number(t.proposed_card_count || 0), 0);

  const approve = async () => {
    setBusy(true);
    setError(null);
    try {
      // Drops apply only now — an accidental tap on Remove lost nothing.
      await api(`/api/jobs/${job.job_id}/plan`, {
        method: "PUT",
        body: JSON.stringify({ topics: kept.map(({ dropped, ...topic }) => topic) }),
      });
      await api(`/api/jobs/${job.job_id}/generate`, { method: "POST" });
      dropCache("/api/jobs");
      onApproved();
    } catch (problem: any) {
      setError(problem.message);
      setBusy(false);
    }
  };

  const fieldStyle = {
    borderWidth: 1, borderColor: palette.border, borderRadius: radius.md,
    paddingHorizontal: space[2], paddingVertical: space[1], minHeight: target.min,
    color: palette.text, fontSize: 16, fontWeight: "600" as const,
    backgroundColor: palette.bg,
  };

  return (
    <Frame
      title="Plan review"
      caption={job.source_filename}
      notice={notice}
      footer={
        <View style={{
          flexDirection: "row", alignItems: "center", gap: space[3],
          paddingHorizontal: space[3], paddingTop: space[2],
          paddingBottom: insets.bottom + space[2],
          backgroundColor: palette.surface, borderTopWidth: 1, borderTopColor: palette.border,
        }}>
          <View style={{ flex: 1 }}>
            <T v="secondary" style={{ fontWeight: "600", fontVariant: ["tabular-nums"] }}>
              {kept.length} topics · ~{totalCards} cards
            </T>
            <Cap>nothing runs until you approve</Cap>
          </View>
          <Button title={busy ? "Starting…" : "Approve & generate"}
            onPress={approve} disabled={busy || !kept.length} />
        </View>
      }
    >
      <View style={{ backgroundColor: palette.sunken, borderRadius: radius.md, paddingHorizontal: 14, paddingVertical: 10 }}>
        <T v="secondary" style={{ fontWeight: "600", fontVariant: ["tabular-nums"] }}>
          {kept.length} topics · ~{totalCards} cards
          {estimate === undefined ? " · estimating…"
            : estimate === null ? ""
            : ` · est $${estimate.estimated_cost_usd.toFixed(2)}`}
        </T>
      </View>
      {estimate === null && (
        <Cap>Estimate unavailable — you can still generate.</Cap>
      )}
      {estimate && !estimate.within_limit && (
        <ErrorCard message={`Over the ${estimate.token_ceiling.toLocaleString()}-token limit — remove a file and re-upload.`} />
      )}
      <Cap>
        Nothing is generated until you approve. It is much cheaper to fix a
        plan than a deck.
      </Cap>

      <View style={{ gap: space[2] }}>
        {topics.map((topic, index) =>
          topic.dropped ? (
            <CardBox key={topic.topic_id}
              style={{ padding: 14, opacity: 0.55, flexDirection: "row", alignItems: "center", gap: 10 }}>
              <T v="body" color={palette.muted}
                style={{ flex: 1, fontWeight: "600", textDecorationLine: "line-through" }}>
                {topic.path.split("::").pop()}
              </T>
              <Pressable onPress={() => edit(index, { dropped: false })}
                style={{ minHeight: target.min, justifyContent: "center", paddingHorizontal: space[1] }}>
                <T v="secondary" color={palette.accent} style={{ fontWeight: "600" }}>Restore</T>
              </Pressable>
            </CardBox>
          ) : (
            <CardBox key={topic.topic_id} style={{ padding: 14, gap: 10 }}>
              <TextInput value={topic.path} style={fieldStyle}
                onChangeText={(path) => edit(index, { path })} />
              {topic.rationale ? <Cap>{topic.rationale}</Cap> : null}
              <View style={{ flexDirection: "row", alignItems: "center", gap: space[1], flexWrap: "wrap" }}>
                <View style={{ flexGrow: 1, flexBasis: 150 }}>
                  <Seg options={[["easy", "easy"], ["medium", "medium"], ["hard", "hard"]]}
                    value={topic.difficulty}
                    onChange={(difficulty) => edit(index, { difficulty })} />
                </View>
                <View style={{ flexGrow: 1, flexBasis: 110 }}>
                  <Seg options={[["basic", "basic"], ["cloze", "cloze"]]}
                    value={topic.note_type}
                    onChange={(note_type) => edit(index, { note_type })} />
                </View>
                <View style={{
                  flexDirection: "row", alignItems: "center", gap: 2,
                  borderWidth: 1, borderColor: palette.border, borderRadius: radius.md, padding: 2,
                }}>
                  <IconBtn name="minus" label="Fewer cards"
                    onPress={() => edit(index, { proposed_card_count: Math.max(1, topic.proposed_card_count - 1) })} />
                  <T v="secondary" style={{ fontWeight: "600", fontVariant: ["tabular-nums"], width: 24, textAlign: "center" }}>
                    {topic.proposed_card_count}
                  </T>
                  <IconBtn name="plus" label="More cards"
                    onPress={() => edit(index, { proposed_card_count: Math.min(60, topic.proposed_card_count + 1) })} />
                </View>
                <Pressable onPress={() => edit(index, { dropped: true })}
                  style={{ minHeight: target.min, justifyContent: "center", paddingHorizontal: space[1] }}>
                  <T v="secondary" color={palette.muted}>Remove</T>
                </Pressable>
              </View>
            </CardBox>
          )
        )}
        <Button title="Add topic" kind="ghost"
          onPress={() => setTopics((current) => [...current, {
            topic_id: `${slug("added")}-${current.length}`,
            path: "New topic",
            difficulty: "medium",
            rationale: "",
            note_type: "basic",
            proposed_card_count: 5,
            claims: [],
            dropped: false,
          }])} />
      </View>
      {error && <ErrorCard message={error} />}
    </Frame>
  );
}

// --- generating --------------------------------------------------------------

function Generating({ job, notice }: { job: any; notice?: React.ReactNode }) {
  const router = useRouter();
  const [topics, setTopics] = useState<any[]>([]);
  const [lessonCount, setLessonCount] = useState(0);

  useEffect(() => {
    const tick = () => {
      api(`/api/jobs/${job.job_id}/topics`).then((body) => setTopics(body.topics)).catch(() => {});
      api(`/api/jobs/${job.job_id}/lessons`)
        .then((body) => setLessonCount(body.lessons.length))
        .catch(() => {});
    };
    tick();
    const timer = setInterval(tick, 3000);
    return () => clearInterval(timer);
  }, [job.job_id]);

  const done = topics.filter((t) => t.status === "done").length;
  const current = topics.find((t) => t.status === "running");

  return (
    <Frame title={job.deck_name || job.source_filename} caption="writing lessons and cards" notice={notice}>
      <CardBox style={{ padding: 20, gap: space[2] }}>
        <Hairline fraction={topics.length ? done / topics.length : 0.08} />
        <T v="secondary" style={{ fontVariant: ["tabular-nums"] }}>
          {done} of {topics.length || "…"} topics
          {current ? ` · writing ${current.path.split("::").pop()}` : ""}
        </T>
        <Cap>You can leave — this keeps running.</Cap>
      </CardBox>
      <Button title={lessonCount > 0 ? `Read lessons (${lessonCount} ready)` : "The first lesson is being written…"}
        disabled={lessonCount === 0}
        onPress={() => router.push(`/lessons/${job.job_id}`)} />
      <Button title="Review the cards written so far" kind="ghost"
        onPress={() => router.push(`/job/${job.job_id}/cards`)} />
    </Frame>
  );
}
