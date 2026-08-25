// The study session. The rule that shapes everything here: a rating never
// waits on the network. Answers go to the local queue and the UI advances
// instantly; the queue flushes in idempotent batches behind the person's
// back, and the only trace of the network is the quiet sync pill.
import { useLocalSearchParams, useRouter } from "expo-router";
import { useGoBack } from "../../lib/nav";
import React, { useCallback, useEffect, useRef, useState } from "react";
import { Pressable, ScrollView, TextInput, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { cached, dropCache, dueCounts } from "../../lib/data";
import { enqueue, flush, pendingCount, removeQueued, subscribe, uuid } from "../../lib/queue";
import { api } from "../../lib/session";
import { radius, space, target, usePalette } from "../../theme";
import { Button, Cap, CardBox, CardText, ErrorCard, Icon, IconBtn, Pill, Sheet, Skeleton, T, useToast } from "../../ui";

const RATING_META: [string, string][] = [
  ["again", "Again"], ["hard", "Hard"], ["good", "Good"], ["easy", "Easy"],
];

export default function Study() {
  const { deckId } = useLocalSearchParams<{ deckId: string }>();
  const router = useRouter();
  const goBack = useGoBack();
  const toast = useToast();
  const palette = usePalette();
  const insets = useSafeAreaInsets();

  const [queue, setQueue] = useState<any[] | null>(null);
  const [revealed, setRevealed] = useState(false);
  const [log, setLog] = useState<any[]>([]);
  const [pending, setPending] = useState(pendingCount());
  const [menu, setMenu] = useState<null | "overflow" | "edit" | "info">(null);
  const [error, setError] = useState<string | null>(null);
  const [baselineKnown, setBaselineKnown] = useState<number | null>(null);
  const shownAt = useRef(Date.now());
  const deckName = useRef("");

  const load = useCallback(async () => {
    setError(null);
    setQueue(null);
    setLog([]);
    try {
      let cards: any[] = [];
      if (deckId === "all") {
        // Chain every deck with work, largest first: one tap, no deciding.
        const { decks } = await api("/api/decks");
        const buckets: any[] = [];
        for (const deck of decks) {
          await api(`/api/decks/${deck.deck_id}/study`, { method: "POST" }).catch(() => {});
          const due = await api(`/api/decks/${deck.deck_id}/due`).catch(() => ({ cards: [] }));
          if (due.cards.length) buckets.push({ deck, cards: due.cards });
        }
        buckets.sort((a, b) => b.cards.length - a.cards.length);
        cards = buckets.flatMap((bucket) => bucket.cards);
        deckName.current = buckets.length === 1 ? buckets[0].deck.name : "All decks";
      } else {
        await api(`/api/decks/${deckId}/study`, { method: "POST" });
        const [due, decks] = await Promise.all([
          api(`/api/decks/${deckId}/due`),
          cached("/api/decks", 60_000),
        ]);
        cards = due.cards;
        deckName.current =
          decks.decks.find((d: any) => d.deck_id === deckId)?.name || "Study";
      }
      setQueue(cards);
      shownAt.current = Date.now();
      cached("/api/leaderboard", 0)
        .then((board: any) => {
          const me = board.rows.find((row: any) => row.is_you);
          setBaselineKnown(me ? me.cards_known : null);
        })
        .catch(() => {});
    } catch (problem: any) {
      setError(problem.message);
    }
  }, [deckId]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => subscribe(setPending), []);

  const card = queue?.[0];

  const rate = useCallback((rating: string) => {
    if (!card) return;
    const review = {
      client_uuid: uuid(),
      card_uuid: card.card_uuid,
      rating,
      reviewed_at: new Date().toISOString(),
      duration_ms: Date.now() - shownAt.current,
    };
    void enqueue(review);
    setLog((entries) => [...entries, { card, rating, client_uuid: review.client_uuid, ms: review.duration_ms }]);
    setQueue((current) => {
      const rest = current!.slice(1);
      // Local re-queue is session convenience, not scheduling authority:
      // the server's next-due wins the moment the queue is refetched.
      if (rating === "again") rest.splice(Math.min(10, rest.length), 0, card);
      if (rating === "hard") rest.push(card);
      return rest;
    });
    setRevealed(false);
    shownAt.current = Date.now();
  }, [card]);

  const undo = useCallback(() => {
    setLog((entries) => {
      if (!entries.length) return entries;
      const last = entries[entries.length - 1];
      // Unflushed: the rating simply never happened. Flushed: it stands in
      // history, and the next rating supersedes it in event order.
      void removeQueued(last.client_uuid);
      setQueue((current) => {
        const withoutRequeue = [...current!];
        const requeued = withoutRequeue.findIndex((c) => c.card_uuid === last.card.card_uuid);
        if (requeued >= 0 && ["again", "hard"].includes(last.rating)) {
          withoutRequeue.splice(requeued, 1);
        }
        return [last.card, ...withoutRequeue];
      });
      setRevealed(false);
      shownAt.current = Date.now();
      return entries.slice(0, -1);
    });
  }, []);

  if (error) return (
    <View style={{ flex: 1, backgroundColor: palette.bg, padding: space[3], paddingTop: insets.top + space[3] }}>
      <ErrorCard message={error} onRetry={load} />
    </View>
  );
  if (!queue) return (
    <View style={{ flex: 1, backgroundColor: palette.bg, padding: space[3], paddingTop: insets.top + space[3] }}>
      <Skeleton h={200} />
    </View>
  );
  if (!card) return <Complete log={log} deckId={deckId!} baselineKnown={baselineKnown} />;

  const done = log.length;
  const total = done + queue.length;

  return (
    <View style={{ flex: 1, backgroundColor: palette.bg, paddingTop: insets.top, paddingBottom: insets.bottom + space[2] }}>
      <View style={{ flexDirection: "row", alignItems: "center", paddingHorizontal: space[2] }}>
        <IconBtn name="x" label="Stop for now" onPress={() => goBack()} />
        <Cap style={{ flex: 1, textAlign: "center" }}>{deckName.current}</Cap>
        <IconBtn name="dots" label="More" onPress={() => setMenu("overflow")} />
      </View>

      <View style={{ paddingHorizontal: space[4] }}>
        <View style={{ height: 3, borderRadius: 2, backgroundColor: palette.sunken }}>
          <View style={{
            height: 3, borderRadius: 2, backgroundColor: palette.accent,
            width: `${(done / Math.max(1, total)) * 100}%`,
          }} />
        </View>
        <View style={{ flexDirection: "row", justifyContent: "space-between", marginTop: 8 }}>
          <Cap>{done} / {total}</Cap>
          {pending > 0 && <Pill text={`syncing ${pending}`} />}
        </View>
      </View>

      <ScrollView style={{ flex: 1 }} contentContainerStyle={{
        flexGrow: 1, justifyContent: "center", padding: space[5], gap: space[4],
      }}>
        <View>
          <CardText text={card.rendered_front || card.front} />
        </View>
        {revealed && (
          <>
            <View style={{ height: 1, backgroundColor: palette.border }} />
            <T v="body" color={palette.text2} style={{ fontSize: 18, lineHeight: 27 }}>
              {card.back || card.front}
            </T>
            <Cap>{card.deck_path}</Cap>
          </>
        )}
      </ScrollView>

      <View style={{ paddingHorizontal: space[3], gap: space[2] }}>
        {revealed ? (
          <View style={{ flexDirection: "row", gap: space[2] }}>
            {RATING_META.map(([key, label]) => (
              <Pressable key={key} onPress={() => rate(key)}
                style={({ pressed }) => ({
                  flex: 1, minHeight: target.rating, borderRadius: radius.md,
                  borderWidth: 1, alignItems: "center", justifyContent: "center", gap: 1,
                  borderColor: key === "again" ? palette.danger : key === "good" ? palette.accent : palette.borderStrong,
                  backgroundColor: pressed ? palette.sunken : palette.surface,
                })}>
                <T v="secondary" style={{
                  fontWeight: "600",
                  color: key === "again" ? palette.danger : key === "good" ? palette.accent : palette.text,
                }}>
                  {label}
                </T>
                {card.previews?.[key] && <Cap style={{ fontVariant: ["tabular-nums"] }}>{card.previews[key]}</Cap>}
              </Pressable>
            ))}
          </View>
        ) : (
          <Button title="Show answer" style={{ minHeight: target.rating }} onPress={() => setRevealed(true)} />
        )}
      </View>

      {menu === "overflow" && (
        <Sheet onClose={() => setMenu(null)}>
          <Button title="Edit card" kind="ghost" onPress={() => setMenu("edit")} />
          <Button title="Card info" kind="ghost" onPress={() => setMenu("info")} />
          <Button title="Undo last" kind="ghost" disabled={!log.length}
            onPress={() => { undo(); setMenu(null); }} />
        </Sheet>
      )}
      {menu === "edit" && (
        <EditSheet card={card} onClose={() => setMenu(null)}
          onSaved={(front: string, back: string) => {
            setQueue((current) => [
              { ...current![0], front, back, rendered_front: current![0].note_type === "cloze" ? current![0].rendered_front : front },
              ...current!.slice(1),
            ]);
            setMenu(null);
            toast("Card updated");
          }} />
      )}
      {menu === "info" && (
        <Sheet onClose={() => setMenu(null)}>
          <T v="heading">Card info</T>
          <InfoRow label="State" value={card.state} />
          <InfoRow label="Reviews" value={card.reps} />
          {card.stability != null && <InfoRow label="Stability" value={`${card.stability.toFixed(1)} d`} />}
          <InfoRow label="Due" value={new Date(card.due).toLocaleString()} />
          <InfoRow label="Deck path" value={card.deck_path} />
        </Sheet>
      )}
    </View>
  );
}

function InfoRow({ label, value }: { label: string; value: any }) {
  return (
    <View style={{ flexDirection: "row", justifyContent: "space-between", gap: space[3], minHeight: 28 }}>
      <T v="secondary">{label}</T>
      <T v="secondary" style={{ fontWeight: "600", fontVariant: ["tabular-nums"], flexShrink: 1 }}>
        {String(value)}
      </T>
    </View>
  );
}

export function EditSheet({ card, onClose, onSaved }: { card: any; onClose: () => void; onSaved: (f: string, b: string) => void }) {
  const palette = usePalette();
  const [front, setFront] = useState(card.front);
  const [back, setBack] = useState(card.back);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const field = {
    borderWidth: 1, borderColor: palette.border, borderRadius: radius.md,
    padding: space[3], minHeight: 88, color: palette.text, fontSize: 16,
    textAlignVertical: "top" as const, backgroundColor: palette.bg,
  };

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await api(`/api/cards/${card.card_uuid}`, {
        method: "PATCH",
        body: JSON.stringify({ front, back }),
      });
      onSaved(front, back);
    } catch (problem: any) {
      setError(problem.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Sheet onClose={onClose}>
      <T v="heading">Edit card</T>
      <TextInput multiline value={front} onChangeText={setFront} style={field} />
      <TextInput multiline value={back} onChangeText={setBack} style={field} />
      {error && <T v="secondary" color={palette.danger}>{error}</T>}
      <View style={{ flexDirection: "row", gap: space[2] }}>
        <Button title="Cancel" kind="ghost" style={{ flex: 1 }} onPress={onClose} />
        <Button title="Save" style={{ flex: 1 }} onPress={save} disabled={busy} />
      </View>
    </Sheet>
  );
}

function Complete({ log, deckId, baselineKnown }: { log: any[]; deckId: string; baselineKnown: number | null }) {
  const router = useRouter();
  const goBack = useGoBack();
  const toast = useToast();
  const palette = usePalette();
  const insets = useSafeAreaInsets();
  const [board, setBoard] = useState<any>(null);
  const [nextDeck, setNextDeck] = useState<any>(null);
  const [missOpen, setMissOpen] = useState(false);
  const [editing, setEditing] = useState<any>(null);

  useEffect(() => {
    (async () => {
      // The final ratings may still be sitting in the local queue; land
      // them first, or the summary counts the pre-session world.
      await flush().catch(() => {});
      dropCache("/api");
      api("/api/leaderboard").then(setBoard).catch(() => {});
      api("/api/decks")
        .then(async ({ decks }: any) => {
          const counts = await dueCounts(decks);
          const candidates = decks
            .filter((deck: any) => deck.deck_id !== deckId && (counts[deck.deck_id] || 0) > 0)
            .sort((a: any, b: any) => counts[b.deck_id]! - counts[a.deck_id]!);
          if (candidates.length) {
            setNextDeck({ ...candidates[0], due: counts[candidates[0].deck_id] });
          }
        })
        .catch(() => {});
    })();
  }, [deckId]);

  const reviewed = log.length;
  const misses = [...new Map(
    log.filter((entry) => entry.rating === "again").map((entry) => [entry.card.card_uuid, entry.card])
  ).values()];
  const correct = reviewed ? Math.round(((reviewed - log.filter((e) => e.rating === "again").length) / reviewed) * 100) : 0;
  const totalMs = log.reduce((sum, entry) => sum + (entry.ms || 0), 0);
  const minutes = Math.floor(totalMs / 60000);
  const seconds = Math.round((totalMs % 60000) / 1000);
  const me = board?.rows.find((row: any) => row.is_you);
  const ahead = board?.rows.find((row: any) => !row.is_you && row.reviews > (me?.reviews ?? 0));
  const knownDelta = me && baselineKnown != null ? me.cards_known - baselineKnown : null;

  const stat = (value: any, label: string, small?: boolean) => (
    <View style={{
      flexBasis: "48%", flexGrow: 1, backgroundColor: palette.sunken,
      borderRadius: radius.md, padding: 14, gap: 2,
    }}>
      <T style={{ fontSize: small ? 16 : 22, lineHeight: 26, fontWeight: "600", fontVariant: ["tabular-nums"] }}>
        {value}
      </T>
      <Cap>{label}</Cap>
    </View>
  );

  return (
    <ScrollView style={{ flex: 1, backgroundColor: palette.bg }}
      contentContainerStyle={{ padding: space[3], paddingTop: insets.top + space[6], paddingBottom: insets.bottom + space[4], gap: space[4], flexGrow: 1 }}>
      <View style={{ alignItems: "center", gap: space[3] }}>
        <View style={{
          width: 56, height: 56, borderRadius: radius.pill, borderWidth: 3,
          borderColor: palette.accent, alignItems: "center", justifyContent: "center",
        }}>
          <Icon name="check" size={26} color={palette.accent} />
        </View>
        <T v="title">Session complete</T>
      </View>

      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: space[2] }}>
        {stat(reviewed, "reviewed")}
        {stat(`${correct}%`, "correct")}
        {stat(`${minutes}:${String(seconds).padStart(2, "0")}`, "time")}
        {stat(me?.streak_days ? `Day ${me.streak_days} kept` : "—", "streak", true)}
      </View>

      {me && (
        <T v="secondary" style={{ textAlign: "center", fontVariant: ["tabular-nums"] }}>
          Known {me.cards_known}{knownDelta && knownDelta > 0 ? ` (+${knownDelta})` : ""}
          {ahead ? ` · ${ahead.display_name || "A friend"} is ${ahead.reviews - me.reviews} reviews ahead this week` : ""}
        </T>
      )}

      {misses.length > 0 && (
        <CardBox style={{ gap: 10 }}>
          <Pressable onPress={() => setMissOpen(!missOpen)}
            style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", minHeight: 28 }}>
            <T v="heading">{misses.length} card{misses.length > 1 ? "s" : ""} missed</T>
            <Icon name="chevD" size={16} color={palette.muted} />
          </Pressable>
          {missOpen && misses.map((card) => (
            <View key={card.card_uuid} style={{ gap: 6, borderTopWidth: 1, borderTopColor: palette.border, paddingTop: 10 }}>
              <T v="body" style={{ fontWeight: "600" }}>{card.rendered_front || card.front}</T>
              <T v="secondary">{card.back}</T>
              <View style={{ flexDirection: "row" }}>
                <Button title="Edit" kind="ghost" onPress={() => setEditing(card)} />
              </View>
            </View>
          ))}
        </CardBox>
      )}

      <View style={{ gap: space[2], marginTop: "auto" }}>
        {nextDeck ? (
          <Button title={`Next: ${nextDeck.name} — ${nextDeck.due} due`}
            onPress={() => router.replace(`/study/${nextDeck.deck_id}`)} />
        ) : (
          <Button title="Done" onPress={() => goBack()} />
        )}
        <Button title="Back to Today" kind="ghost" onPress={() => goBack()} />
      </View>

      {editing && (
        <EditSheet card={editing} onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); toast("Card updated"); }} />
      )}
    </ScrollView>
  );
}
