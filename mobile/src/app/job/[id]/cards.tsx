// Post-generation card review — and the moment the pipeline finally lands in
// the product's own loop: the terminal action is "Study these now", not a
// download. The .apkg export lives on the deck screen, web-side.
import { useLocalSearchParams, useRouter } from "expo-router";
import React, { useCallback, useEffect, useRef, useState } from "react";
import { Pressable, ScrollView, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { dropCache } from "../../../lib/data";
import { api } from "../../../lib/session";
import { radius, space, target, usePalette } from "../../../theme";
import { Button, Cap, CardBox, ErrorCard, Icon, IconBtn, Pill, Skeleton, T, useToast } from "../../../ui";
import { EditSheet } from "../../study/[deckId]";

// The web's btn-small, without dropping under the touch floor.
const btnSmall = { paddingHorizontal: space[2] };

export default function CardsReview() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const toast = useToast();
  const palette = usePalette();
  const insets = useSafeAreaInsets();

  const [cards, setCards] = useState<any[] | null>(null);
  const [job, setJob] = useState<any>(null);
  const [picked, setPicked] = useState<Set<string>>(() => new Set());
  const [editing, setEditing] = useState<any>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Soft-deletes: uuid -> timer. The DELETE fires after the undo window.
  const doomed = useRef(new Map<string, ReturnType<typeof setTimeout>>());

  const load = useCallback(async () => {
    setError(null);
    try {
      const [body, jobBody] = await Promise.all([
        api(`/api/jobs/${id}/cards`),
        api(`/api/jobs/${id}`),
      ]);
      setCards(body.cards);
      setJob(jobBody);
    } catch (problem: any) {
      setError(problem.message);
    }
  }, [id]);

  useEffect(() => { load(); }, [load]);

  if (error) return (
    <View style={{ flex: 1, backgroundColor: palette.bg, padding: space[3], paddingTop: insets.top + space[3] }}>
      <ErrorCard message={error} onRetry={load} />
    </View>
  );
  if (!cards) return (
    <View style={{ flex: 1, backgroundColor: palette.bg, padding: space[3], paddingTop: insets.top + space[3], gap: space[2] }}>
      <Skeleton h={60} />
      <Skeleton h={200} />
    </View>
  );

  const byTopic = cards.reduce((groups: Record<string, any[]>, card: any) => {
    (groups[card.deck_path] ||= []).push(card);
    return groups;
  }, {});
  const keptCount = cards.filter((card) => card.reviewed).length;

  const act = async (label: string, run: () => Promise<void>) => {
    setBusy(label);
    try {
      await run();
    } catch (problem: any) {
      toast(problem.message);
    } finally {
      setBusy(null);
    }
  };

  const keep = (uuids: string[]) =>
    act("keep", async () => {
      await api(`/api/jobs/${id}/cards/accept`, {
        method: "POST",
        body: JSON.stringify({ card_uuids: uuids }),
      });
      setCards((current) =>
        current && current.map((card) => (uuids.includes(card.card_uuid) ? { ...card, reviewed: true } : card)));
      setPicked(new Set());
    });

  const reject = (uuids: string[]) => {
    // Optimistic removal with a 5-second undo; the server hears only if the
    // window passes. Deletion is confirmed by the snackbar, never celebrated.
    setCards((current) => current && current.filter((card) => !uuids.includes(card.card_uuid)));
    setPicked(new Set());
    const timer = setTimeout(() => {
      uuids.forEach((uuid) => doomed.current.delete(uuid));
      api(`/api/jobs/${id}/cards/reject`, {
        method: "POST",
        body: JSON.stringify({ card_uuids: uuids }),
      }).catch(() => load());
    }, 5000);
    uuids.forEach((uuid) => doomed.current.set(uuid, timer));
    toast(`${uuids.length} card${uuids.length > 1 ? "s" : ""} rejected`, {
      action: "Undo",
      ttl: 5000,
      onAction: () => {
        clearTimeout(timer);
        uuids.forEach((uuid) => doomed.current.delete(uuid));
        load();
      },
    });
  };

  const reroll = (card: any) =>
    act(card.card_uuid, async () => {
      await api(`/api/cards/${card.card_uuid}/reroll`, { method: "POST" });
      const body = await api(`/api/jobs/${id}/cards`);
      // The selection survives a single-card action — no losing forty ticks
      // to one re-roll.
      setCards(body.cards);
    });

  const studyNow = () =>
    act("study", async () => {
      await api(`/api/decks/${job.deck_id}/study`, { method: "POST" });
      dropCache("/api");
      router.replace(`/study/${job.deck_id}`);
    });

  const toggle = (uuid: string) =>
    setPicked((current) => {
      const next = new Set(current);
      next.has(uuid) ? next.delete(uuid) : next.add(uuid);
      return next;
    });

  return (
    <View style={{ flex: 1, backgroundColor: palette.bg, paddingTop: insets.top }}>
      <View style={{ flexDirection: "row", alignItems: "center", paddingHorizontal: space[2] }}>
        <IconBtn name="chevL" label="Back" onPress={() => router.back()} />
        <Cap style={{ flex: 1, textAlign: "center" }}>Look them over</Cap>
        <View style={{ width: target.min }} />
      </View>

      <ScrollView
        style={{ flex: 1 }}
        contentContainerStyle={{
          padding: space[3], paddingTop: space[0], gap: space[3],
          // Clear the bulk bar the way the web pads for .bulkbar.
          paddingBottom: insets.bottom + (picked.size ? 96 : space[6]),
        }}
      >
        <Cap>A bad card gets drilled for weeks before you notice — this is where it dies instead.</Cap>

        <View>
          <View style={{ height: 4, borderRadius: 2, backgroundColor: palette.sunken, overflow: "hidden" }}>
            <View style={{
              height: 4, borderRadius: 2, backgroundColor: palette.accent,
              width: `${cards.length ? (keptCount / cards.length) * 100 : 0}%`,
            }} />
          </View>
          <Cap style={{ marginTop: 6, fontVariant: ["tabular-nums"] }}>
            {keptCount} of {cards.length} kept
          </Cap>
        </View>

        {Object.entries(byTopic).map(([path, group]) => (
          <View key={path} style={{ gap: space[1] }}>
            <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: space[1] }}>
              <T v="heading" style={{ flex: 1 }}>{path.split("::").pop()}</T>
              <Pressable
                onPress={() => setPicked((current) => {
                  const next = new Set(current);
                  group.forEach((card) => next.add(card.card_uuid));
                  return next;
                })}
                style={{ minHeight: target.min, justifyContent: "center" }}
              >
                <Cap color={palette.accent} style={{ fontWeight: "600" }}>
                  Select all {group.length}
                </Cap>
              </Pressable>
            </View>
            {group.map((card) => (
              <View key={card.card_uuid} style={{
                flexDirection: "row", gap: 10,
                backgroundColor: palette.surface, borderWidth: 1, borderRadius: radius.md,
                borderColor: picked.has(card.card_uuid) ? palette.accent : palette.border,
                paddingHorizontal: 14, paddingVertical: space[2],
              }}>
                <Pressable
                  onPress={() => toggle(card.card_uuid)}
                  accessibilityRole="checkbox"
                  accessibilityState={{ checked: picked.has(card.card_uuid) }}
                  hitSlop={{ top: 12, bottom: 12, left: 12, right: 10 }}
                  style={{
                    width: 22, height: 22, marginTop: 2, borderRadius: radius.sm,
                    borderWidth: 1.5, alignItems: "center", justifyContent: "center",
                    borderColor: picked.has(card.card_uuid) ? palette.accent : palette.borderStrong,
                    backgroundColor: picked.has(card.card_uuid) ? palette.accent : "transparent",
                  }}
                >
                  {picked.has(card.card_uuid) && <Icon name="check" size={14} color={palette.onAccent} />}
                </Pressable>
                <View style={{ flex: 1, gap: space[0] }}>
                  <T v="body" style={{ fontWeight: "600" }}>{card.rendered_front || card.front}</T>
                  {card.back ? <T v="secondary">{card.back}</T> : null}
                  {card.downgraded && (
                    <View style={{
                      alignSelf: "flex-start", borderRadius: radius.pill,
                      paddingHorizontal: 10, paddingVertical: 3, backgroundColor: palette.warningSoft,
                    }}>
                      <Cap color={palette.warning}>cloze had no deletion — sent as basic</Cap>
                    </View>
                  )}
                  <View style={{ flexDirection: "row", flexWrap: "wrap", gap: space[0] }}>
                    {!card.reviewed ? (
                      <Button title="Keep" kind="ghost" style={btnSmall} onPress={() => keep([card.card_uuid])} />
                    ) : (
                      <View style={{ justifyContent: "center" }}><Pill text="kept" /></View>
                    )}
                    <Button title="Edit" kind="ghost" style={btnSmall} onPress={() => setEditing(card)} />
                    <Button
                      title={busy === card.card_uuid ? "Asking again…" : "Re-roll"}
                      kind="ghost" style={btnSmall}
                      disabled={busy === card.card_uuid}
                      onPress={() => reroll(card)}
                    />
                    <Button title="Reject" kind="danger" style={btnSmall} onPress={() => reject([card.card_uuid])} />
                  </View>
                </View>
              </View>
            ))}
          </View>
        ))}

        {cards.length > 0 && job && (
          <CardBox style={{ gap: space[1] }}>
            <T v="heading">{cards.length} cards ready</T>
            <Button title="Study these now" onPress={studyNow} disabled={busy === "study"} />
            <Button title="Later" kind="ghost" onPress={() => router.push(`/deck/${job.deck_id}`)} />
          </CardBox>
        )}
      </ScrollView>

      {picked.size > 0 && (
        <View style={{
          position: "absolute", left: 0, right: 0, bottom: 0,
          flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 10,
          paddingHorizontal: space[3], paddingTop: space[2], paddingBottom: insets.bottom + space[3],
          backgroundColor: palette.surface, borderTopWidth: 1, borderTopColor: palette.border,
        }}>
          <T v="secondary" style={{ fontWeight: "600", fontVariant: ["tabular-nums"] }}>
            {picked.size} selected
          </T>
          <Button title={`Keep ${picked.size}`} onPress={() => keep([...picked])} disabled={busy === "keep"} />
          <Button title={`Reject ${picked.size}`} kind="danger" onPress={() => reject([...picked])} />
        </View>
      )}

      {editing && (
        <EditSheet card={editing} onClose={() => setEditing(null)}
          onSaved={(front: string, back: string) => {
            setCards((current) =>
              current && current.map((c) => (c.card_uuid === editing.card_uuid
                ? { ...c, front, back, rendered_front: c.note_type === "cloze" ? c.rendered_front : front }
                : c)));
            setEditing(null);
            toast("Card updated");
          }} />
      )}
    </View>
  );
}
