// The deck library: yours, then what friends gave you. Rows navigate; every
// action lives in deck detail, because inline blur-save rename is dead.
import { useRouter } from "expo-router";
import React, { useCallback, useEffect, useState } from "react";
import { View } from "react-native";
import { cached, dueCounts } from "../../lib/data";
import { space } from "../../theme";
import { Cap, CardBox, Button, ErrorCard, IconBtn, NavRow, Pill, Screen, Skeleton, T, useToast } from "../../ui";

export default function Decks() {
  const router = useRouter();
  const toast = useToast();
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

  useEffect(() => { load(); }, [load]);

  // Same message as Today's plus button: the upload flow is web-only for now.
  const uploadElsewhere = () =>
    toast("Uploading a lecture lands on mobile next — use the web app for now.");

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
        <IconBtn name="plus" label="Add a lecture" onPress={uploadElsewhere} />
      </View>

      {decks.length === 0 && (
        <CardBox style={{ gap: space[2] }}>
          <T v="heading">Nothing here yet</T>
          <T v="secondary">Upload a lecture and this fills itself.</T>
          <Button title="Add your first lecture" onPress={uploadElsewhere} />
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
    </Screen>
  );
}
