// One running upload, as a card that says what is actually happening: "Plan
// for X" while the material is being read, live topic counts while lessons
// and cards are written. Tapping always lands on the job screen — the only
// place with the full story — never on an empty deck.
import { type Href, useRouter } from "expo-router";
import React from "react";
import { ActivityIndicator, Pressable, View } from "react-native";
import { PLANNING_STATES } from "../lib/live-jobs";
import { radius, space, target, usePalette } from "../theme";
import { Cap, T } from "./index";

// The states where the run is waiting on a person, not a model.
const NEEDS_YOU: Record<string, { line: string; action: string }> = {
  plan_ready: { line: "Plan ready", action: "Review & approve" },
  failed: { line: "Hit a problem", action: "Retry" },
  interrupted: { line: "Interrupted", action: "Resume" },
  dead: { line: "Stopped after repeated failures", action: "Start again" },
};

export function JobProgressCard({ job }: { job: any }) {
  const router = useRouter();
  const palette = usePalette();
  const name = job.deck_name || job.source_filename || "Your upload";
  const planning = PLANNING_STATES.includes(job.state);
  const needs = NEEDS_YOU[job.state];
  const total = job.topics_total || 0;
  const done = job.topics_done || 0;

  if (needs)
    return (
      <Pressable
        onPress={() => router.push(`/job/${job.job_id}` as Href)}
        style={{
          flexDirection: "row", alignItems: "center", gap: space[3],
          backgroundColor: palette.accentSoft, borderRadius: radius.md,
          paddingHorizontal: 14, paddingVertical: 12, minHeight: target.min,
        }}
      >
        <View style={{ flex: 1 }}>
          <T v="secondary" style={{ fontWeight: "600", color: palette.text }} numberOfLines={1}>
            {name}
          </T>
          <Cap>{job.state === "failed" ? job.error || needs.line : needs.line}</Cap>
        </View>
        <T v="secondary" style={{ fontWeight: "600", color: palette.accent }}>{needs.action}</T>
      </Pressable>
    );

  return (
    <Pressable
      onPress={() => router.push(`/job/${job.job_id}` as Href)}
      style={({ pressed }) => ({
        gap: 8,
        backgroundColor: pressed ? palette.sunken : palette.surface,
        borderWidth: 1,
        borderColor: palette.border,
        borderRadius: radius.md,
        paddingHorizontal: 14,
        paddingVertical: 12,
        minHeight: target.min,
      })}
    >
      <View style={{ flexDirection: "row", alignItems: "center", gap: space[2] }}>
        <ActivityIndicator size="small" color={palette.accent} />
        <View style={{ flex: 1 }}>
          <T v="secondary" style={{ fontWeight: "600", color: palette.text }} numberOfLines={1}>
            {planning ? `Plan for ${name}` : `Writing ${name}`}
          </T>
          <Cap>
            {planning
              ? "Reading the material into topics — a minute or two"
              : total
                ? `${done} of ${total} topics · ${job.card_count || 0} cards so far`
                : "Starting the first topic…"}
          </Cap>
        </View>
      </View>
      {!planning && total > 0 && (
        <View style={{ height: 3, borderRadius: 2, backgroundColor: palette.sunken, overflow: "hidden" }}>
          <View
            style={{
              height: 3,
              borderRadius: 2,
              backgroundColor: palette.accent,
              width: `${Math.max(4, (done / total) * 100)}%`,
            }}
          />
        </View>
      )}
    </Pressable>
  );
}
