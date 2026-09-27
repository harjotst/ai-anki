// A deck, full screen over the home page: study it, browse its topics and
// cards, read the document it was made from, rename or delete it. New
// material is a new deck — a deck is one upload. The .apkg export lands in
// the cache and leaves through the system share sheet.
import * as FileSystem from "expo-file-system/legacy";
import { type Href, useLocalSearchParams, useRouter } from "expo-router";
import { useGoBack } from "../../../lib/nav";
import * as Sharing from "expo-sharing";
import React, { useCallback, useEffect, useState } from "react";
import { Pressable, ScrollView, TextInput, View, ViewStyle } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { answerText } from "../../../lib/cloze";
import { cached, dropCache } from "../../../lib/data";
import { api, authHeaders, BASE } from "../../../lib/session";
import { radius, space, target, usePalette } from "../../../theme";
import { Button, Cap, ClozeFilled, ErrorCard, Icon, IconBtn, Pill, Seg, Sheet, Skeleton, T, useToast } from "../../../ui";
import { EditSheet } from "../../study/[deckId]";

export default function DeckDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const goBack = useGoBack();
  const toast = useToast();
  const palette = usePalette();
  const insets = useSafeAreaInsets();

  const [deck, setDeck] = useState<any>(null);
  const [due, setDue] = useState<any[] | null>(null);
  const [mastery, setMastery] = useState<any>(null);
  const [jobs, setJobs] = useState<any[]>([]);
  const [deckJobs, setDeckJobs] = useState<any[]>([]);
  const [segment, setSegment] = useState("topics");
  const [cards, setCards] = useState<any[] | null>(null);
  const [search, setSearch] = useState("");
  const [menu, setMenu] = useState<null | "dots" | "rename" | "delete">(null);
  const [editing, setEditing] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [studyBusy, setStudyBusy] = useState(false);
  const [exportBusy, setExportBusy] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const removeDeck = async () => {
    setDeleting(true);
    try {
      await api(`/api/decks/${id}`, { method: "DELETE" });
      dropCache("/api");
      toast("Deck deleted");
      router.replace("/");
    } catch (problem: any) {
      toast(problem.message);
      setDeleting(false);
    }
  };

  const load = useCallback(async () => {
    setError(null);
    try {
      const [deckList, jobList, deckJobList] = await Promise.all([
        cached("/api/decks", 30_000),
        cached("/api/jobs", 30_000),
        // The deck's finished jobs, newest first: where its lessons live and
        // what an export is built from.
        cached(`/api/decks/${id}/jobs`, 30_000).catch(() => ({ jobs: [] })),
      ]);
      const found = deckList.decks.find((d: any) => d.deck_id === id);
      if (!found) throw new Error("no such deck");
      setDeck(found);
      setJobs(jobList.jobs.filter((job: any) => job.deck_id === id));
      setDeckJobs(deckJobList.jobs);
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

  const latestCompleteJob = deckJobs[0];

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
      // update=true: the server ships only cards never exported plus, when
      // asked, edited ones — without asking, any re-export after edits still
      // 409s with "nothing new".
      const result = await FileSystem.downloadAsync(
        `${BASE}/api/jobs/${latestCompleteJob.job_id}/deck.apkg?update=true`,
        `${FileSystem.cacheDirectory}${name}.apkg`,
        { headers: (await authHeaders()) as Record<string, string> },
      );
      // downloadAsync saves error bodies instead of throwing; on a non-200
      // the file on disk is the server's JSON error, so read its detail —
      // "nothing new to download" beats a cryptic status code.
      if (result.status !== 200) {
        const body = await FileSystem.readAsStringAsync(result.uri).catch(() => "");
        let detail: string | undefined;
        try { detail = JSON.parse(body).detail; } catch { /* not JSON */ }
        await FileSystem.deleteAsync(result.uri, { idempotent: true }).catch(() => {});
        throw new Error(detail || `export failed (${result.status})`);
      }
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
        <IconBtn name="chevL" label="Back" onPress={() => goBack()} />
        <Cap style={{ flex: 1, textAlign: "center" }}>{deck.name}</Cap>
        <IconBtn name="dots" label="More" onPress={() => setMenu("dots")} />
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
        </Cap>

        <Button
          title={studyBusy ? "Opening…" : due?.length ? `Study ${due.length} due` : "Study ahead"}
          onPress={startStudy}
          disabled={studyBusy}
        />

        <Button title={exportBusy ? "Exporting…" : "Export"} kind="ghost"
          disabled={exportBusy} onPress={exportDeck} />

        <Seg
          options={[["topics", "Topics"], ["cards", "Cards"], ["document", "Document"]]}
          value={segment}
          onChange={setSegment}
        />

        {segment === "topics" && (
          <View style={{ gap: space[2] }}>
            {!mastery && <Skeleton h={52} />}
            {mastery?.topics.map((topic: any) => {
              const topicId =
                topic.topic_id ||
                (due || []).find((c: any) => c.deck_path === topic.deck_path)?.topic_id;
              // Counted by deck_path directly: imported decks stamp every
              // card topic_id 'imported', so any topic_id-keyed count hands
              // each subdeck row the whole deck's due pile.
              const dueHere = (due || []).filter((c: any) => c.deck_path === topic.deck_path).length;
              const pct = Math.round(topic.mastery * 100);
              return (
                <Pressable key={topic.deck_path}
                  onPress={() => {
                    // 'imported' marks cards that arrived in an .apkg — no
                    // lesson exists behind them, so the row goes nowhere.
                    if (topicId && topicId !== "imported" && latestCompleteJob)
                      router.push(`/deck/${id}/topic/${topicId}`);
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
                      {card.note_type === "cloze" ? (
                        <>
                          <ClozeFilled text={card.front} size={16} numberOfLines={2} />
                          {!!card.back && card.back !== card.front && (
                            <T v="caption" numberOfLines={1}>{card.back}</T>
                          )}
                        </>
                      ) : (
                        <>
                          <T v="body" style={{ fontWeight: "600" }} numberOfLines={1}>{card.front}</T>
                          <T v="caption" numberOfLines={1} style={{ letterSpacing: 0.2 }}>{answerText(card)}</T>
                        </>
                      )}
                    </View>
                    <Icon name="edit" size={16} color={palette.muted} />
                  </Pressable>
                ))}
            </View>
          </>
        )}

        {/* The document the deck was made from, opened in a reader. An
            imported .apkg has no document behind it, so it is named only. */}
        {segment === "document" && (
          <View style={{ gap: space[2] }}>
            {jobs.length === 0 && <T v="secondary">No document for this deck.</T>}
            {jobs.map((job) => {
              const name = job.source_filename || "Imported deck";
              const readable = !!job.source_filename && !/\.apkg$/i.test(job.source_filename);
              return (
                <Pressable key={job.job_id} disabled={!readable}
                  onPress={() => router.push(
                    `/job/${job.job_id}/source?name=${encodeURIComponent(name)}` as Href)}
                  style={({ pressed }) => navrow(pressed)}>
                  <Icon name="doc" size={18} color={palette.muted} />
                  <View style={{ flex: 1, gap: 2 }}>
                    <T v="body" style={{ fontWeight: "600" }} numberOfLines={2}>{name}</T>
                    <Cap>Uploaded {new Date(job.created_at).toLocaleDateString()}</Cap>
                  </View>
                  {readable && <Icon name="chevR" size={16} color={palette.muted} />}
                </Pressable>
              );
            })}
          </View>
        )}
      </ScrollView>

      {menu === "dots" && (
        <Sheet onClose={() => setMenu(null)}>
          <Button title="Rename" kind="ghost" onPress={() => setMenu("rename")} />
          <Button title="Delete deck" kind="ghost" onPress={() => setMenu("delete")} />
        </Sheet>
      )}
      {menu === "delete" && (
        <Sheet onClose={() => setMenu(null)}>
          <T v="heading">Delete this deck?</T>
          <T v="secondary">
            “{deck.name}” goes away for good — all {deck.card_count} cards,
            every lesson, its uploaded document.
            Reviews already done stay counted. This cannot be undone.
          </T>
          <View style={{ flexDirection: "row", gap: space[2] }}>
            <Button title="Cancel" kind="ghost" style={{ flex: 1 }} onPress={() => setMenu(null)} />
            <Button
              title={deleting ? "Deleting…" : "Delete deck"}
              style={{ flex: 1, backgroundColor: palette.danger }}
              disabled={deleting}
              onPress={removeDeck}
            />
          </View>
        </Sheet>
      )}
      {menu === "rename" && (
        <RenameSheet deck={deck} onClose={() => setMenu(null)}
          onDone={(name: string) => { setDeck({ ...deck, name }); setMenu(null); dropCache("/api/decks"); }} />
      )}
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
