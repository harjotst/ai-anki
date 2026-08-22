// The leaderboard, named what it is and living in primary navigation — a
// native mirror of the web screen: same columns, same definitions, same
// friend-code flow. Copy/share collapse into one native Share.
import { useRouter } from "expo-router";
import React, { useCallback, useEffect, useState } from "react";
import { Platform, Pressable, Share, TextInput, View } from "react-native";
import { cached, dropCache } from "../../lib/data";
import { api } from "../../lib/session";
import { radius, space, target, usePalette } from "../../theme";
import {
  Button, Cap, CardBox, ErrorCard, Icon, IconBtn, NavRow, Screen, Skeleton, T, useToast,
} from "../../ui";

const DEFINITIONS: Record<string, string> = {
  reviews: "How many answers were given in the window — work done, not knowledge held.",
  streak: "Consecutive days with at least one review, ending today.",
  known: "Cards you would recall right now. Unlike a review count, it goes down when you stop.",
};

export default function Leaderboard() {
  const router = useRouter();
  const toast = useToast();
  const palette = usePalette();
  const [board, setBoard] = useState<any>(null);
  const [circle, setCircle] = useState<any>(null);
  const [me, setMe] = useState<any>(null);
  const [decks, setDecks] = useState<any[]>([]);
  const [code, setCode] = useState("");
  const [tip, setTip] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [boardBody, circleBody, meBody, deckBody] = await Promise.all([
        api("/api/leaderboard"),
        api("/api/friends"),
        cached("/api/me", 300_000),
        cached("/api/decks", 60_000),
      ]);
      setBoard(boardBody);
      setCircle(circleBody);
      setMe(meBody);
      setDecks(deckBody.decks);
    } catch (problem: any) {
      setError(problem.message);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  if (error) return <Screen><ErrorCard message={error} onRetry={load} /></Screen>;
  if (!board || !circle || !me) return (
    <Screen><Skeleton h={40} /><Skeleton h={180} /><Skeleton h={80} /></Screen>
  );

  const add = async () => {
    try {
      await api("/api/friends", {
        method: "POST",
        body: JSON.stringify({ code: code.trim().toUpperCase() }),
      });
      setCode("");
      dropCache("/api/friends");
      toast("Request sent");
      load();
    } catch (problem: any) {
      toast(problem.message);
    }
  };

  const act = async (path: string, options: any) => {
    try {
      await api(path, options);
      dropCache("/api/friends");
      load();
    } catch (problem: any) {
      toast(problem.message);
    }
  };

  // Column header: tapping toggles the definition line, as on the web.
  // hitSlop lifts the visually small target to the 44pt floor.
  const header = (key: string, label: string, width: number) => (
    <Pressable
      key={key}
      onPress={() => setTip(tip === key ? null : key)}
      hitSlop={{ top: 10, bottom: 10 }}
      style={{
        width, minHeight: 24, flexDirection: "row",
        justifyContent: "flex-end", alignItems: "center", gap: 3,
      }}
    >
      <Cap style={{ textAlign: "right", flexShrink: 1 }}>{label}</Cap>
      <Icon name="info" size={11} color={palette.text2} />
    </Pressable>
  );

  return (
    <Screen>
      <T v="title">Leaderboard</T>

      {circle.incoming.map((person: any) => (
        <View key={person.account_id} style={{
          flexDirection: "row", alignItems: "center", gap: 10,
          backgroundColor: palette.accentSoft, borderRadius: radius.md,
          paddingVertical: space[2], paddingLeft: 14, paddingRight: space[2],
        }}>
          <T v="secondary" style={{ flex: 1, fontWeight: "600" }}>
            {person.display_name || "Somebody"} wants to study with you
          </T>
          <Button title="Accept"
            onPress={() => act(`/api/friends/${person.account_id}/accept`, { method: "POST" })} />
          <Button title="Decline" kind="ghost"
            onPress={() => act(`/api/friends/${person.account_id}`, { method: "DELETE" })} />
        </View>
      ))}

      <CardBox style={{ padding: 6 }}>
        <View style={{
          flexDirection: "row", alignItems: "center", gap: 10,
          paddingHorizontal: 14, paddingTop: 8, paddingBottom: 4,
        }}>
          <View style={{ width: 18 }} />
          <View style={{ flex: 1 }} />
          {header("reviews", "Reviews (this wk)", 96)}
          {header("streak", "Streak", 52)}
          {header("known", "Known", 52)}
        </View>
        {tip && (
          <Cap style={{ paddingHorizontal: 14, paddingBottom: 8 }}>{DEFINITIONS[tip]}</Cap>
        )}
        {board.rows.map((row: any, index: number) => (
          <View key={row.account_id} style={{
            flexDirection: "row", alignItems: "center", gap: 10,
            paddingHorizontal: 14, paddingVertical: 12, minHeight: 52,
            backgroundColor: row.is_you ? palette.accentSoft : "transparent",
            borderRadius: radius.md,
          }}>
            <T v="secondary" color={palette.muted}
              style={{ width: 18, fontVariant: ["tabular-nums"] }}>
              {index + 1}
            </T>
            <T numberOfLines={1} style={{ flex: 1, fontWeight: row.is_you ? "600" : "500" }}>
              {row.is_you ? "You" : row.display_name || row.account_id.slice(0, 8)}
            </T>
            <T style={{ width: 96, textAlign: "right", fontVariant: ["tabular-nums"] }}>
              {row.reviews}
            </T>
            <T style={{ width: 52, textAlign: "right", fontVariant: ["tabular-nums"] }}>
              {row.streak_days ? `${row.streak_days}d` : "—"}
            </T>
            <T style={{ width: 52, textAlign: "right", fontVariant: ["tabular-nums"] }}>
              {row.cards_known}
            </T>
          </View>
        ))}
      </CardBox>
      <Cap>
        Reviews is work done this week. Known is what you would recall right now —
        it goes down if you stop, which a review count never does.
      </Cap>

      <View style={{ flexDirection: "row", gap: space[2] }}>
        <TextInput
          value={code}
          onChangeText={setCode}
          placeholder="a friend's code"
          placeholderTextColor={palette.muted}
          maxLength={12}
          autoCapitalize="characters"
          autoCorrect={false}
          onSubmitEditing={() => { if (code.trim()) add(); }}
          style={{
            flex: 1, minHeight: target.min, borderWidth: 1, borderColor: palette.border,
            borderRadius: radius.md, paddingHorizontal: space[3], fontSize: 16,
            color: palette.text, backgroundColor: palette.surface,
          }}
        />
        <Button title="Add" onPress={add} disabled={!code.trim()} />
      </View>

      <CardBox style={{ flexDirection: "row", alignItems: "center", gap: space[3] }}>
        <View style={{ flex: 1 }}>
          <Cap>Your friend code</Cap>
          <T style={{
            fontSize: 17, lineHeight: 24, letterSpacing: 2.4, fontWeight: "600", marginTop: 2,
            fontFamily: Platform.OS === "ios" ? "Menlo" : "monospace",
          }}>
            {me.friend_code}
          </T>
        </View>
        <IconBtn name="share" label="Share code" onPress={() => {
          Share.share({
            message: `Study with me on ai-anki — my code is ${me.friend_code}`,
          }).catch(() => {});
        }} />
      </CardBox>

      {circle.friends.length > 0 && decks.length > 0 && (
        <View style={{ gap: space[2] }}>
          <Cap style={{ paddingLeft: 2 }}>Compare on a shared deck</Cap>
          {decks.map((deck: any) => (
            <NavRow key={deck.deck_id} onPress={() => router.push(`/compare/${deck.deck_id}`)}>
              <T v="body" style={{ fontWeight: "600" }}>{deck.name}</T>
            </NavRow>
          ))}
        </View>
      )}

      {circle.outgoing.length > 0 && (
        <Cap>
          Waiting on {circle.outgoing.length} request{circle.outgoing.length > 1 ? "s" : ""} to be accepted.
        </Cap>
      )}
    </Screen>
  );
}
