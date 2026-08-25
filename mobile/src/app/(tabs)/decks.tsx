// The deck library: yours, then what friends gave you. Rows navigate; every
// action lives in deck detail, because inline blur-save rename is dead.
import * as DocumentPicker from "expo-document-picker";
import { type Href, useFocusEffect, useRouter } from "expo-router";
import React, { useCallback, useState } from "react";
import { View } from "react-native";
import { cached, dropCache, dueCounts } from "../../lib/data";
import { upload } from "../../lib/session";
import { space } from "../../theme";
import { Cap, CardBox, Button, ErrorCard, IconBtn, NavRow, Pill, Screen, Skeleton, T, useToast } from "../../ui";

export default function Decks() {
  const router = useRouter();
  const [decks, setDecks] = useState<any[] | null>(null);
  const [counts, setCounts] = useState<Record<string, number | null>>({});
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const { decks: all } = await cached("/api/decks", 30_000);
      setDecks(all);
      setCounts(await dueCounts(all));
    } catch (problem: any) {
      setError(problem.message);
    }
  }, []);

  // On focus, not just mount — due counts move while this tab sits behind
  // a study session, and the cache was dropped when it ended.
  useFocusEffect(useCallback(() => { load(); }, [load]));

  // Href cast: the generated route types refresh only when the dev server
  // runs, and /job/new lands in this same change set.
  const startUpload = () => router.push("/job/new" as Href);
  const toast = useToast();
  const [importing, setImporting] = useState(false);

  // Somebody's existing Anki collection is years of work; it walks in the
  // door as-is. No lessons come with it — nothing taught these cards.
  const importApkg = async () => {
    const picked = await DocumentPicker.getDocumentAsync({
      copyToCacheDirectory: true,
    });
    const asset = picked.assets?.[0];
    if (!asset) return;
    if (!asset.name?.toLowerCase().endsWith(".apkg")) {
      return toast("Pick an .apkg file — export one from Anki with File → Export.");
    }
    setImporting(true);
    try {
      const body = new FormData();
      body.append("file", {
        uri: asset.uri,
        name: asset.name,
        type: "application/octet-stream",
      } as any);
      const result = await upload("/api/decks/import", body);
      dropCache("/api");
      await load();
      toast(`${result.deck_name}: ${result.cards} cards imported`);
      router.push(`/deck/${result.deck_id}` as Href);
    } catch (problem: any) {
      toast(problem.message);
    } finally {
      setImporting(false);
    }
  };

  if (error) return <Screen><ErrorCard message={error} onRetry={load} /></Screen>;
  if (!decks) return <Screen><Skeleton h={56} /><Skeleton h={56} /><Skeleton h={56} /></Screen>;

  const bySection: Record<string, any[]> = {
    Yours: decks.filter((deck) => !deck.shared_with_me),
    "Shared with you": decks.filter((deck) => deck.shared_with_me),
  };

  const row = (deck: any) => (
    <NavRow key={deck.deck_id} onPress={() => router.push(`/deck/${deck.deck_id}`)}
      right={(counts[deck.deck_id] || 0) > 0 ? <Pill text={`${counts[deck.deck_id]} due`} accent /> : undefined}>
      <T v="body" style={{ fontWeight: "600" }}>{deck.name}</T>
      <Cap>
        {deck.card_count} cards
        {deck.shared_with_me ? ` · from ${deck.owner_name}` : ""}
      </Cap>
    </NavRow>
  );

  return (
    <Screen>
      <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
        <T v="title">Decks</T>
        <IconBtn name="plus" label="Add a lecture" onPress={startUpload} />
      </View>

      {decks.length === 0 && (
        <CardBox style={{ gap: space[2] }}>
          <T v="heading">Nothing here yet</T>
          <T v="secondary">Upload a lecture and this fills itself.</T>
          <Button title="Add your first lecture" onPress={startUpload} />
          <Button title={importing ? "Importing…" : "Import an Anki deck"} kind="ghost"
            onPress={importApkg} disabled={importing} />
        </CardBox>
      )}

      {Object.entries(bySection).map(([label, section]) =>
        section.length ? (
          <View key={label} style={{ gap: space[1] }}>
            <Cap style={{ paddingLeft: 2 }}>{label}</Cap>
            {[...section]
              .sort((a, b) => (counts[b.deck_id] || 0) - (counts[a.deck_id] || 0))
              .map(row)}
          </View>
        ) : null
      )}

      {decks.length > 0 && (
        <Button title={importing ? "Importing…" : "Import an Anki deck"} kind="ghost"
          onPress={importApkg} disabled={importing} />
      )}
    </Screen>
  );
}
