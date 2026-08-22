// Deck detail: everything the audit found homeless — rename, sharing, the
// card browser, per-topic mastery, run history — lives here now. The .apkg
// export lands in the cache and leaves through the share sheet: the native
// stand-in for the web's browser download.
import * as FileSystem from "expo-file-system/legacy";
import { type Href, useLocalSearchParams, useRouter } from "expo-router";
import * as Sharing from "expo-sharing";
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Pressable, ScrollView, TextInput, View, ViewStyle } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { cached, dropCache } from "../../../lib/data";
import { api, authHeaders, BASE } from "../../../lib/session";
import { radius, space, target, usePalette } from "../../../theme";
import { Button, Cap, ErrorCard, Icon, IconBtn, Pill, Seg, Sheet, Skeleton, T, useToast } from "../../../ui";
import { EditSheet } from "../../study/[deckId]";

export default function DeckDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const toast = useToast();
  const palette = usePalette();
  const insets = useSafeAreaInsets();

  const [deck, setDeck] = useState<any>(null);
  const [due, setDue] = useState<any[] | null>(null);
  const [mastery, setMastery] = useState<any>(null);
  const [jobs, setJobs] = useState<any[]>([]);
  const [segment, setSegment] = useState("topics");
  const [cards, setCards] = useState<any[] | null>(null);
  const [search, setSearch] = useState("");
  const [menu, setMenu] = useState<null | "dots" | "rename" | "share">(null);
  const [editing, setEditing] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [studyBusy, setStudyBusy] = useState(false);
  const [exportBusy, setExportBusy] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [deckList, jobList] = await Promise.all([
        cached("/api/decks", 30_000),
        cached("/api/jobs", 30_000),
      ]);
      const found = deckList.decks.find((d: any) => d.deck_id === id);
      if (!found) throw new Error("no such deck");
      setDeck(found);
      setJobs(jobList.jobs.filter((job: any) => job.deck_id === id));
      const [dueBody, masteryBody] = await Promise.all([
        api(`/api/decks/${id}/due`).catch(() => ({ cards: [] })),
        api(`/api/decks/${id}/mastery`).catch(() => null),
      ]);
      setDue(dueBody.cards);
      setMastery(masteryBody);
    } catch (problem: any) {
      setError(problem.message);
    }
  }, [id]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (segment === "cards" && cards === null) {
      api(`/api/decks/${id}/cards`).then((body) => setCards(body.cards)).catch(() => setCards([]));
    }
  }, [segment, cards, id]);

  const dueByTopic = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const card of due || []) counts[card.topic_id] = (counts[card.topic_id] || 0) + 1;
    return counts;
  }, [due]);

  const latestCompleteJob = jobs.find((job) => ["complete", "reviewing"].includes(job.state));

  // The same row surface as the web's .navrow.
  const navrow = (pressed: boolean): ViewStyle => ({
    flexDirection: "row", alignItems: "center", gap: 10,
    minHeight: 56, paddingHorizontal: 14, paddingVertical: space[2],
    backgroundColor: pressed ? palette.sunken : palette.surface,
    borderColor: palette.border, borderWidth: 1, borderRadius: radius.md,
  });

  if (error) return (
    <View style={{ flex: 1, backgroundColor: palette.bg, padding: space[3], paddingTop: insets.top + space[3] }}>
      <ErrorCard message={error} onRetry={load} />
    </View>
  );
  if (!deck) return (
    <View style={{ flex: 1, backgroundColor: palette.bg, padding: space[3], paddingTop: insets.top + space[3], gap: space[2] }}>
      <Skeleton h={80} /><Skeleton h={48} /><Skeleton h={200} />
    </View>
  );

  const startStudy = async () => {
    setStudyBusy(true);
    try {
      await api(`/api/decks/${id}/study`, { method: "POST" });
      router.push(`/study/${id}`);
    } catch (problem: any) {
      toast(problem.message);
    } finally {
      // Unlike the web, this screen stays mounted under the study stack, so
      // the button must recover on success too.
      setStudyBusy(false);
    }
  };

  const exportDeck = async () => {
    if (!latestCompleteJob) {
      toast("Nothing generated to export yet");
      return;
    }
    const name = deck.name.replace(/[^\w\- ]+/g, "").trim() || "deck";
    setExportBusy(true);
    try {
      const result = await FileSystem.downloadAsync(
        `${BASE}/api/jobs/${latestCompleteJob.job_id}/deck.apkg`,
        `${FileSystem.cacheDirectory}${name}.apkg`,
        { headers: (await authHeaders()) as Record<string, string> },
      );
      // downloadAsync saves error bodies instead of throwing; check the status.
      if (result.status !== 200) throw new Error(`export failed (${result.status})`);
      await Sharing.shareAsync(result.uri);
    } catch (problem: any) {
      toast(problem.message);
    } finally {
      setExportBusy(false);
    }
  };

  return (
    <View style={{ flex: 1, backgroundColor: palette.bg, paddingTop: insets.top }}>
      <View style={{ flexDirection: "row", alignItems: "center", paddingHorizontal: space[2] }}>
        <IconBtn name="chevL" label="Back" onPress={() => router.back()} />
        <Cap style={{ flex: 1, textAlign: "center" }}>{deck.name}</Cap>
        {deck.shared_with_me ? (
          <View style={{ width: target.min }} />
        ) : (
          <IconBtn name="dots" label="More" onPress={() => setMenu("dots")} />
        )}
      </View>

      <ScrollView
        style={{ flex: 1 }}
        keyboardShouldPersistTaps="handled"
        contentContainerStyle={{
          padding: space[3], paddingTop: space[0], gap: space[3],
          paddingBottom: insets.bottom + space[6],
        }}
      >
        <Cap style={{ textAlign: "center" }}>
          {deck.card_count} cards
          {mastery ? ` · ${mastery.topics.length} topics` : ""}
          {deck.shared_with_me ? ` · from ${deck.owner_name}` : ""}
        </Cap>

        <Button
          title={studyBusy ? "Opening…" : due?.length ? `Study ${due.length} due` : "Study ahead"}
          onPress={startStudy}
          disabled={studyBusy}
        />

        {/* Three-up like the web; the tighter padding stands in for the
            web's smaller font on this row. */}
        <View style={{ flexDirection: "row", gap: space[2] }}>
          <Button title="Add lecture" kind="ghost" style={{ flex: 1, paddingHorizontal: space[1] }}
            disabled={deck.shared_with_me} onPress={() => router.push(`/job/new?deck=${id}` as Href)} />
          <Button title="Share" kind="ghost" style={{ flex: 1, paddingHorizontal: space[1] }}
            disabled={deck.shared_with_me} onPress={() => setMenu("share")} />
          <Button title={exportBusy ? "Exporting…" : "Export .apkg"} kind="ghost"
            style={{ flex: 1, paddingHorizontal: space[1] }}
            disabled={exportBusy} onPress={exportDeck} />
        </View>

        <Seg
          options={[["topics", "Topics"], ["cards", "Cards"], ["history", "History"]]}
          value={segment}
          onChange={setSegment}
        />

        {segment === "topics" && (
          <View style={{ gap: space[2] }}>
            {!mastery && <Skeleton h={52} />}
            {mastery?.topics.map((topic: any) => {
              const topicId = (due || []).find((c: any) => c.deck_path === topic.deck_path)?.topic_id;
              const dueHere = Object.entries(dueByTopic)
                .filter(([tid]) => (due || []).some((c: any) => c.topic_id === tid && c.deck_path === topic.deck_path))
                .reduce((sum, [, n]) => sum + n, 0);
              const pct = Math.round(topic.mastery * 100);
              return (
                <Pressable key={topic.deck_path}
                  onPress={() => {
                    if (topicId && latestCompleteJob) router.push(`/deck/${id}/topic/${topicId}`);
                  }}
                  style={({ pressed }) => navrow(pressed)}>
                  <View style={{ flex: 1, gap: 2 }}>
                    <T v="body" style={{ fontWeight: "600" }} numberOfLines={1}>
                      {topic.deck_path.split("::").pop()}
                    </T>
                    {/* Copy rule: decayed retrievability is "due for review",
                        never "forgotten". */}
                    {pct < 40 && topic.mastery > 0 && <Cap>due for review</Cap>}
                  </View>
                  <View style={{ width: 56, height: 4, borderRadius: 2, backgroundColor: palette.sunken, overflow: "hidden" }}>
                    <View style={{ width: `${pct}%`, height: 4, borderRadius: 2, backgroundColor: palette.accent }} />
                  </View>
                  <Cap style={{ width: 34, textAlign: "right", fontWeight: "600", fontVariant: ["tabular-nums"] }}>
                    {pct}%
                  </Cap>
                  {dueHere > 0 && <Pill text={String(dueHere)} accent />}
                </Pressable>
              );
            })}
            {mastery && !mastery.topics.length && (
              <T v="secondary">No cards yet — generation may still be running.</T>
            )}
          </View>
        )}

        {segment === "cards" && (
          <>
            <TextInput
              value={search}
              onChangeText={setSearch}
              placeholder="Search cards"
              placeholderTextColor={palette.muted}
              style={{
                minHeight: target.min, borderWidth: 1, borderColor: palette.border,
                borderRadius: radius.sm, paddingHorizontal: space[2],
                backgroundColor: palette.surface, color: palette.text, fontSize: 16,
              }}
            />
            <View style={{ gap: space[2] }}>
              {cards === null && <Skeleton h={52} />}
              {(cards || [])
                .filter((card) =>
                  (card.front + card.back).toLowerCase().includes(search.toLowerCase()))
                .slice(0, 100)
                .map((card) => (
                  <Pressable key={card.card_uuid} onPress={() => setEditing(card)}
                    style={({ pressed }) => navrow(pressed)}>
                    <View style={{ flex: 1, gap: 2 }}>
                      <T v="body" style={{ fontWeight: "600" }} numberOfLines={1}>{card.front}</T>
                      <T v="caption" numberOfLines={1} style={{ letterSpacing: 0.2 }}>{card.back}</T>
                    </View>
                    <Icon name="edit" size={16} color={palette.muted} />
                  </Pressable>
                ))}
            </View>
          </>
        )}

        {segment === "history" && (
          <View style={{ gap: space[2] }}>
            {jobs.length === 0 && <T v="secondary">No uploads yet.</T>}
            {jobs.map((job) => (
              <View key={job.job_id} style={navrow(false)}>
                <View style={{ flex: 1, gap: 2 }}>
                  <T v="secondary" style={{ fontWeight: "600", color: palette.text }} numberOfLines={1}>
                    {job.source_filename}
                  </T>
                  <Cap>
                    {new Date(job.created_at).toLocaleDateString()} ·{" "}
                    {job.state === "failed" ? job.error || "failed" : job.state}
                    {job.card_count ? ` · ${job.card_count} cards` : ""}
                  </Cap>
                </View>
                {["interrupted", "failed", "plan_ready", "generating", "planning"].includes(job.state) && (
                  <Button kind="ghost" onPress={() => router.push(`/job/${job.job_id}` as Href)}
                    title={job.state === "interrupted" ? "Resume" : job.state === "failed" ? "Retry" : "Open"} />
                )}
              </View>
            ))}
          </View>
        )}
      </ScrollView>

      {menu === "dots" && (
        <Sheet onClose={() => setMenu(null)}>
          <Button title="Rename" kind="ghost" onPress={() => setMenu("rename")} />
        </Sheet>
      )}
      {menu === "rename" && (
        <RenameSheet deck={deck} onClose={() => setMenu(null)}
          onDone={(name: string) => { setDeck({ ...deck, name }); setMenu(null); dropCache("/api/decks"); }} />
      )}
      {menu === "share" && <ShareSheet deckId={id!} onClose={() => setMenu(null)} />}
      {editing && (
        <EditSheet card={editing} onClose={() => setEditing(null)}
          onSaved={(front: string, back: string) => {
            setCards((current) =>
              current && current.map((c) => (c.card_uuid === editing.card_uuid ? { ...c, front, back } : c)));
            setEditing(null);
            toast("Card updated");
          }} />
      )}
    </View>
  );
}

function RenameSheet({ deck, onClose, onDone }: { deck: any; onClose: () => void; onDone: (name: string) => void }) {
  const palette = usePalette();
  const [name, setName] = useState(deck.name);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    setError(null);
    try {
      await api(`/api/decks/${deck.deck_id}`, {
        method: "PATCH",
        body: JSON.stringify({ name }),
      });
      onDone(name);
    } catch (problem: any) {
      // An explicit inline error, never a silent revert.
      setError(problem.message);
    }
  };

  return (
    <Sheet onClose={onClose}>
      <T v="heading">Rename deck</T>
      <TextInput
        value={name}
        onChangeText={setName}
        autoFocus
        style={{
          minHeight: target.min, borderWidth: 1, borderColor: palette.border,
          borderRadius: radius.sm, paddingHorizontal: space[2],
          backgroundColor: palette.bg, color: palette.text, fontSize: 16,
        }}
      />
      {error && <T v="secondary" color={palette.danger}>{error}</T>}
      <View style={{ flexDirection: "row", gap: space[2] }}>
        <Button title="Cancel" kind="ghost" style={{ flex: 1 }} onPress={onClose} />
        <Button title="Save" style={{ flex: 1 }} onPress={save} disabled={!name.trim()} />
      </View>
    </Sheet>
  );
}

function ShareSheet({ deckId, onClose }: { deckId: string; onClose: () => void }) {
  const router = useRouter();
  const toast = useToast();
  const [friends, setFriends] = useState<any[] | null>(null);

  useEffect(() => {
    api("/api/friends").then((circle) => setFriends(circle.friends)).catch(() => setFriends([]));
  }, []);

  const give = async (person: any) => {
    try {
      await api(`/api/decks/${deckId}/share`, {
        method: "POST",
        body: JSON.stringify({ account_id: person.account_id }),
      });
      toast(`Shared with ${person.display_name || "them"}`);
      onClose();
    } catch (problem: any) {
      toast(problem.message);
    }
  };

  return (
    <Sheet onClose={onClose}>
      <T v="heading">Share this deck</T>
      {friends === null && <Skeleton h={44} />}
      {friends?.length === 0 && (
        <>
          <T v="secondary">
            Sharing needs a friend first — add one with their code on the Leaderboard.
          </T>
          <Button title="Go to Leaderboard"
            onPress={() => { onClose(); router.push("/leaderboard"); }} />
        </>
      )}
      {friends?.map((person) => (
        <Button key={person.account_id} kind="ghost"
          title={person.display_name || person.account_id.slice(0, 8)}
          onPress={() => give(person)} />
      ))}
    </Sheet>
  );
}
