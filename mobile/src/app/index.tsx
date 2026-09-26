// Home: the whole app on one page. What is due today, then the decks. The
// account lives behind the avatar in the corner, and the only thing it does
// is sign out. A deck opens full screen; everything else is pushed over this.
import * as DocumentPicker from "expo-document-picker";
import { type Href, useFocusEffect, useRouter } from "expo-router";
import React, { useCallback, useEffect, useState } from "react";
import { Image, Modal, Pressable, RefreshControl, ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { cached, dropCache, dueCounts } from "../lib/data";
import { deckStillForming, LIVE_STATES, useLiveJobs } from "../lib/live-jobs";
import { avatarUrl, signOut, uploadFile } from "../lib/session";
import { radius, space, target, usePalette } from "../theme";
import { Button, Cap, CardBox, ErrorCard, IconBtn, NavRow, Pill, Skeleton, T, useToast } from "../ui";
import { JobProgressCard } from "../ui/job-progress";
import { Mascot } from "../ui/mascot";

// Runs a person can still do something about — live, or waiting on them.
const OPEN_STATES = [...LIVE_STATES, "plan_ready", "failed", "interrupted", "dead"];

const AVATAR = 36;

export default function Home() {
  const router = useRouter();
  const palette = usePalette();
  const toast = useToast();
  const insets = useSafeAreaInsets();
  const [decks, setDecks] = useState<any[] | null>(null);
  const [counts, setCounts] = useState<Record<string, number | null>>({});
  // Decks land a beat before due counts do; until the counts resolve,
  // "nothing due" would be a guess, and a wrong one flashes "All caught up".
  const [countsReady, setCountsReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [importing, setImporting] = useState(false);
  // Every running upload, polled while anything is live; `pulse` bumps when
  // a state changes, so a plan turning ready shows here without a refresh.
  const { jobs: liveJobs, pulse } = useLiveJobs();

  const load = useCallback(async () => {
    setError(null);
    try {
      const { decks: all } = await cached("/api/decks", 30_000);
      setDecks(all);
      setCounts(await dueCounts(all));
      setCountsReady(true);
    } catch (problem: any) {
      setError(problem.message);
    }
  }, []);

  // On focus, not just mount: coming back from a study session (which drops
  // the cache) or a deck must show the new numbers without a reload.
  useFocusEffect(useCallback(() => { load(); }, [load]));
  useEffect(() => { if (pulse) load(); }, [pulse, load]);

  const newDeck = () => router.push("/job/new" as Href);

  // Somebody's existing Anki collection is years of work; it walks in the
  // door as-is. No lessons come with it — nothing taught these cards.
  const importApkg = async () => {
    const picked = await DocumentPicker.getDocumentAsync({ copyToCacheDirectory: true });
    const asset = picked.assets?.[0];
    if (!asset) return;
    if (!asset.name?.toLowerCase().endsWith(".apkg")) {
      return toast("Pick an .apkg file — export one from Anki with File → Export.");
    }
    setImporting(true);
    try {
      const result = await uploadFile("/api/decks/import", asset.uri, {
        mimeType: "application/octet-stream",
      });
      dropCache("/api");
      await load();
      toast(`${result.deck_name}: ${result.cards} cards imported`);
      router.push(`/deck/${result.deck_id}`);
    } catch (problem: any) {
      toast(problem.message);
    } finally {
      setImporting(false);
    }
  };

  const body = () => {
    if (error) return <ErrorCard message={error} onRetry={load} />;
    if (!decks) return (
      <>
        <Skeleton h={150} r={radius.lg} />
        <Skeleton /><Skeleton /><Skeleton />
      </>
    );

    const openJobs = (liveJobs || []).filter((job) => OPEN_STATES.includes(job.state));
    // A deck still being made is represented by its run, never by an empty
    // shell that opens onto nothing.
    const settled = decks.filter((deck) => !deckStillForming(deck, liveJobs));
    const totalDue = settled.reduce((sum, deck) => sum + (counts[deck.deck_id] || 0), 0);
    const decksWithDue = settled.filter((deck) => (counts[deck.deck_id] || 0) > 0).length;
    const firstRun = settled.length === 0 && openJobs.length === 0;

    return (
      <>
        {firstRun ? (
          <CardBox style={{ gap: space[3], alignItems: "center" }}>
            <Mascot size={120} />
            <T v="heading">Make your first deck</T>
            <T v="secondary" style={{ textAlign: "center" }}>
              Upload a lecture, approve the plan, and the cards arrive here.
              Then study a little every day — what is due shows up at the top.
            </T>
            <Button title="Upload a lecture" style={{ alignSelf: "stretch" }} onPress={newDeck} />
            <Button title={importing ? "Importing…" : "Import an Anki deck"} kind="ghost"
              style={{ alignSelf: "stretch" }} onPress={importApkg} disabled={importing} />
          </CardBox>
        ) : !countsReady ? (
          <Skeleton h={150} r={radius.lg} />
        ) : (
          <CardBox style={{ padding: space[5] }}>
            {totalDue > 0 ? (
              <>
                <T v="statXl" style={{ fontVariant: ["tabular-nums"] }}>{totalDue}</T>
                <T v="secondary" style={{ marginTop: 2 }}>
                  card{totalDue === 1 ? "" : "s"} due today
                  {decksWithDue > 1 ? ` · ${decksWithDue} decks` : ""}
                </T>
                <Button title="Start reviewing" style={{ marginTop: space[4], minHeight: target.rating }}
                  onPress={() => router.push("/study/all")} />
              </>
            ) : (
              <>
                <T v="heading">All caught up</T>
                <T v="secondary" style={{ marginTop: 2 }}>Nothing is due today.</T>
                {settled.length > 0 && (
                  <Button title="Study ahead" kind="ghost" style={{ marginTop: space[4] }}
                    onPress={() => router.push("/study/all")} />
                )}
              </>
            )}
          </CardBox>
        )}

        {!firstRun && (
          <View style={{ gap: space[2] }}>
            <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
              <T v="heading">Decks</T>
              <IconBtn name="plus" label="New deck" onPress={newDeck} />
            </View>

            {openJobs.map((job) => <JobProgressCard key={job.job_id} job={job} />)}

            {[...settled]
              .sort((a, b) => (counts[b.deck_id] || 0) - (counts[a.deck_id] || 0))
              .map((deck) => (
                <NavRow key={deck.deck_id} onPress={() => router.push(`/deck/${deck.deck_id}`)}
                  right={(counts[deck.deck_id] || 0) > 0
                    ? <Pill text={`${counts[deck.deck_id]} due`} accent />
                    : undefined}>
                  <T v="body" style={{ fontWeight: "600" }} numberOfLines={1}>{deck.name}</T>
                  <Cap>{deck.card_count} card{deck.card_count === 1 ? "" : "s"}</Cap>
                </NavRow>
              ))}

            <Button title={importing ? "Importing…" : "Import an Anki deck"} kind="ghost"
              style={{ marginTop: space[2] }} onPress={importApkg} disabled={importing} />
          </View>
        )}
      </>
    );
  };

  return (
    <ScrollView
      style={{ flex: 1, backgroundColor: palette.bg }}
      contentContainerStyle={{
        padding: space[3], gap: space[3],
        paddingTop: insets.top + space[2], paddingBottom: insets.bottom + space[6],
      }}
      refreshControl={
        <RefreshControl refreshing={refreshing} onRefresh={async () => {
          setRefreshing(true);
          dropCache("/api");
          await load();
          setRefreshing(false);
        }} />
      }
    >
      <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
        <View>
          <T v="title">Today</T>
          <Cap>{new Date().toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" })}</Cap>
        </View>
        <AccountMenu />
      </View>
      {body()}
    </ScrollView>
  );
}

/** The avatar in the corner, and the one thing behind it: signing out. */
function AccountMenu() {
  const palette = usePalette();
  const insets = useSafeAreaInsets();
  const [open, setOpen] = useState(false);
  const [me, setMe] = useState<any>(null);
  const [picture, setPicture] = useState<string | null>(null);

  useEffect(() => {
    cached("/api/me", 300_000).then(setMe).catch(() => {});
    avatarUrl().then(setPicture).catch(() => {});
  }, []);

  const initial = (me?.display_name || me?.email || "?").trim().charAt(0).toUpperCase();

  return (
    <>
      <Pressable
        onPress={() => setOpen(true)}
        accessibilityLabel="Account"
        hitSlop={(target.min - AVATAR) / 2}
        style={({ pressed }) => ({
          width: AVATAR, height: AVATAR, borderRadius: AVATAR / 2, overflow: "hidden",
          alignItems: "center", justifyContent: "center",
          backgroundColor: palette.accentSoft, opacity: pressed ? 0.75 : 1,
        })}
      >
        {picture ? (
          <Image source={{ uri: picture }} style={{ width: AVATAR, height: AVATAR }}
            onError={() => setPicture(null)} />
        ) : (
          <Text style={{ color: palette.accent, fontSize: 16, fontWeight: "600" }}>{initial}</Text>
        )}
      </Pressable>

      <Modal visible={open} transparent animationType="fade" onRequestClose={() => setOpen(false)}>
        <Pressable style={{ flex: 1 }} onPress={() => setOpen(false)} accessibilityLabel="Close">
          <View style={{
            position: "absolute", top: insets.top + space[2] + AVATAR + space[1], right: space[3],
            minWidth: 180, backgroundColor: palette.surface, borderRadius: radius.md,
            borderWidth: 1, borderColor: palette.border, overflow: "hidden",
          }}>
            <Pressable
              onPress={async () => {
                setOpen(false);
                dropCache();
                await signOut();
              }}
              style={({ pressed }) => ({
                minHeight: target.min, justifyContent: "center", paddingHorizontal: space[4],
                backgroundColor: pressed ? palette.sunken : palette.surface,
              })}
            >
              <T v="body" color={palette.danger}>Sign out</T>
            </Pressable>
          </View>
        </Pressable>
      </Modal>
    </>
  );
}
