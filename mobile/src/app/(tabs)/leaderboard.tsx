// The leaderboard is about people now: friends are names you can say out
// loud, not codes you paste. Requests come first as cards, the week's board
// is the centerpiece, and your own handle sits at the bottom ready to share.
// The friend code still works server-side; it gets no pixels here.
import { useRouter } from "expo-router";
import React, { useCallback, useEffect, useState } from "react";
import { Pressable, Share, TextInput, View } from "react-native";
import { cached, dropCache } from "../../lib/data";
import { api } from "../../lib/session";
import { radius, space, target, usePalette } from "../../theme";
import {
  Button, Cap, CardBox, ErrorCard, Icon, IconBtn, NavRow, Screen, Sheet,
  Skeleton, T, useToast,
} from "../../ui";

// The web's column definitions, kept whole but moved off the screen into a
// single sheet — one quiet ⓘ instead of three tappable headers.
const DEFINITIONS: [string, string][] = [
  ["Reviews", "How many answers were given in the window — work done, not knowledge held."],
  ["Streak", "Consecutive days with at least one review, ending today."],
  ["Known", "Cards you would recall right now. Unlike a review count, it goes down when you stop."],
];

// A person is a letter in a circle before they are a row of numbers.
function Avatar({ name }: { name?: string | null }) {
  const palette = usePalette();
  const initial = (name || "").trim().charAt(0).toUpperCase() || "?";
  return (
    <View style={{
      width: 36, height: 36, borderRadius: radius.pill,
      backgroundColor: palette.accentSoft,
      alignItems: "center", justifyContent: "center",
    }}>
      <T v="secondary" color={palette.accent} style={{ fontWeight: "600" }}>
        {initial}
      </T>
    </View>
  );
}

export default function Leaderboard() {
  const router = useRouter();
  const toast = useToast();
  const palette = usePalette();
  const [board, setBoard] = useState<any>(null);
  const [circle, setCircle] = useState<any>(null);
  const [me, setMe] = useState<any>(null);
  const [decks, setDecks] = useState<any[]>([]);
  const [handle, setHandle] = useState("");
  const [sheet, setSheet] = useState<null | "info" | "compare">(null);
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
    <Screen>
      <Skeleton h={28} /><Skeleton h={220} r={radius.lg} />
      <Skeleton h={44} /><Skeleton h={64} />
    </Screen>
  );

  const add = async () => {
    const wanted = handle.trim();
    if (!wanted) return;
    try {
      await api("/api/friends", {
        method: "POST",
        body: JSON.stringify({ username: wanted }),
      });
      setHandle("");
      dropCache("/api/friends");
      toast("Request sent");
      load();
    } catch (problem: any) {
      // The server's 404 detail is precise but stiff; say it like a person.
      toast(/nobody by/i.test(problem.message) ? "Nobody by that name." : problem.message);
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

  const hasFriends = circle.friends.length > 0;
  const you = me.username ? `@${me.username}` : null;
  const share = () => {
    Share.share({ message: `Add me on ai-anki: @${me.username}` }).catch(() => {});
  };

  // The one way in: a name. Used inline when friends exist, and inside the
  // welcome card when none do yet.
  const addField = (
    <View style={{ flexDirection: "row", gap: space[2] }}>
      <TextInput
        value={handle}
        onChangeText={setHandle}
        placeholder="@username"
        placeholderTextColor={palette.muted}
        autoCapitalize="none"
        autoCorrect={false}
        maxLength={21}
        onSubmitEditing={add}
        style={{
          flex: 1, minHeight: target.min, borderWidth: 1, borderColor: palette.border,
          borderRadius: radius.md, paddingHorizontal: space[3], fontSize: 16,
          color: palette.text, backgroundColor: palette.surface,
        }}
      />
      <Button title="Add" onPress={add} disabled={!handle.trim()} />
    </View>
  );

  return (
    <Screen>
      <T v="title">Leaderboard</T>

      {circle.incoming.map((person: any) => (
        <CardBox key={person.account_id} style={{ gap: space[3] }}>
          <View style={{ flexDirection: "row", alignItems: "center", gap: space[3] }}>
            <Avatar name={person.display_name || person.username} />
            <View style={{ flex: 1 }}>
              <T numberOfLines={1} style={{ fontWeight: "600" }}>
                {person.display_name || (person.username ? `@${person.username}` : "Somebody")}
              </T>
              <Cap>
                {person.username ? `@${person.username} · ` : ""}wants to study with you
              </Cap>
            </View>
          </View>
          <View style={{ flexDirection: "row", gap: space[2] }}>
            <Button title="Accept" style={{ flex: 1 }}
              onPress={() => act(`/api/friends/${person.account_id}/accept`, { method: "POST" })} />
            <Button title="Decline" kind="ghost" style={{ flex: 1 }}
              onPress={() => act(`/api/friends/${person.account_id}`, { method: "DELETE" })} />
          </View>
        </CardBox>
      ))}

      {hasFriends ? (
        <>
          <CardBox style={{ padding: space[1] }}>
            <View style={{
              flexDirection: "row", alignItems: "center",
              paddingHorizontal: space[2], paddingTop: space[1], paddingBottom: space[1],
            }}>
              <Cap style={{ flex: 1 }}>Reviews · last 7 days</Cap>
              {/* hitSlop lifts the small glyph to the 44pt floor. */}
              <Pressable
                onPress={() => setSheet("info")}
                accessibilityLabel="What the numbers mean"
                hitSlop={{ top: 14, bottom: 14, left: 14, right: 14 }}
              >
                <Icon name="info" size={15} color={palette.muted} />
              </Pressable>
            </View>
            {board.rows.map((row: any, index: number) => {
              const name = row.is_you
                ? "You"
                : row.display_name || (row.username ? `@${row.username}` : "Somebody");
              const parts: string[] = [];
              if (row.streak_days) parts.push(`${row.streak_days}d streak`);
              parts.push(`${row.cards_known} known`);
              return (
                <View key={row.account_id} style={{
                  flexDirection: "row", alignItems: "center", gap: space[2],
                  paddingHorizontal: space[2], paddingVertical: 10, minHeight: 56,
                  backgroundColor: row.is_you ? palette.accentSoft : "transparent",
                  borderRadius: radius.md,
                }}>
                  <T v="secondary"
                    color={index === 0 ? palette.accent : palette.muted}
                    style={{
                      width: 22, fontVariant: ["tabular-nums"],
                      fontWeight: index === 0 ? "600" : "400",
                    }}>
                    {index + 1}
                  </T>
                  <Avatar name={row.display_name || row.username} />
                  <View style={{ flex: 1 }}>
                    <T numberOfLines={1} style={{ fontWeight: row.is_you ? "600" : "500" }}>
                      {name}
                    </T>
                    {row.username ? <Cap>@{row.username}</Cap> : null}
                  </View>
                  <View style={{ alignItems: "flex-end" }}>
                    <T v="heading" style={{ fontVariant: ["tabular-nums"] }}>{row.reviews}</T>
                    <Cap style={{ fontVariant: ["tabular-nums"] }}>{parts.join(" · ")}</Cap>
                  </View>
                </View>
              );
            })}
          </CardBox>

          {decks.length > 0 && (
            <NavRow onPress={() => (
              decks.length === 1
                ? router.push(`/compare/${decks[0].deck_id}`)
                : setSheet("compare")
            )}>
              <T v="body" style={{ fontWeight: "600" }}>Compare on a deck</T>
              <Cap>Topic by topic, against a friend</Cap>
            </NavRow>
          )}

          <View style={{ gap: space[2] }}>
            <Cap style={{ paddingLeft: 2 }}>Add a friend</Cap>
            {addField}
          </View>
        </>
      ) : (
        <CardBox style={{ gap: space[3] }}>
          <Cap>Study with friends</Cap>
          {you ? (
            <>
              <T v="display">{you}</T>
              <T v="secondary">
                Friends add each other by name. Share yours, add theirs, and
                the week's numbers land here.
              </T>
              <Button title="Share your username" onPress={share} />
              {addField}
            </>
          ) : (
            <>
              <T v="heading">First, pick a username</T>
              <T v="secondary">
                Friends add each other by name — claim yours and the board
                fills in from there.
              </T>
              <Button title="Choose a username" onPress={() => router.push("/you")} />
            </>
          )}
        </CardBox>
      )}

      {circle.outgoing.length > 0 && (
        <Cap>
          Waiting on {circle.outgoing
            .map((p: any) => (p.username ? `@${p.username}` : p.display_name || "somebody"))
            .join(", ")} to accept.
        </Cap>
      )}

      {hasFriends && (you ? (
        <CardBox style={{ flexDirection: "row", alignItems: "center", gap: space[3] }}>
          <View style={{ flex: 1 }}>
            <T style={{ fontWeight: "600" }}>You're {you}</T>
            <Cap>Friends add you by name</Cap>
          </View>
          <IconBtn name="share" label="Share your username" onPress={share} />
        </CardBox>
      ) : (
        <NavRow onPress={() => router.push("/you")}>
          <T v="body" style={{ fontWeight: "600" }}>Pick a username</T>
          <Cap>Friends add you by name</Cap>
        </NavRow>
      ))}

      {sheet === "info" && (
        <Sheet onClose={() => setSheet(null)}>
          <T v="heading">What the numbers mean</T>
          {DEFINITIONS.map(([term, meaning]) => (
            <View key={term} style={{ gap: 2 }}>
              <Cap>{term}</Cap>
              <T v="secondary">{meaning}</T>
            </View>
          ))}
        </Sheet>
      )}

      {sheet === "compare" && (
        <Sheet onClose={() => setSheet(null)}>
          <T v="heading">Compare on a deck</T>
          {decks.map((deck: any) => (
            <Pressable
              key={deck.deck_id}
              onPress={() => { setSheet(null); router.push(`/compare/${deck.deck_id}`); }}
              style={({ pressed }) => ({
                minHeight: target.min, justifyContent: "center",
                paddingHorizontal: space[2], borderRadius: radius.md,
                backgroundColor: pressed ? palette.sunken : "transparent",
              })}
            >
              <T style={{ fontWeight: "600" }}>{deck.name}</T>
            </Pressable>
          ))}
        </Sheet>
      )}
    </Screen>
  );
}
