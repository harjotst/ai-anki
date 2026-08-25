// Topic-by-topic comparison on a shared deck — one friend at a time, with the
// grinder's actual question answered by the gap sort: where are they ahead?
import { useLocalSearchParams, useRouter } from "expo-router";
import { useGoBack } from "../../lib/nav";
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { ScrollView, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { cached } from "../../lib/data";
import { api } from "../../lib/session";
import { radius, space, target, usePalette } from "../../theme";
import { Button, Cap, CardBox, ErrorCard, IconBtn, Pill, Seg, Skeleton, T } from "../../ui";

export default function Compare() {
  const { deckId } = useLocalSearchParams<{ deckId: string }>();
  const router = useRouter();
  const goBack = useGoBack();
  const palette = usePalette();
  const insets = useSafeAreaInsets();

  const [compared, setCompared] = useState<any>(null);
  const [deckName, setDeckName] = useState("");
  const [friend, setFriend] = useState<string | null>(null);
  const [sort, setSort] = useState("gap");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [body, decks] = await Promise.all([
        api(`/api/decks/${deckId}/compare`),
        cached("/api/decks", 60_000),
      ]);
      setCompared(body);
      setDeckName(decks.decks.find((d: any) => d.deck_id === deckId)?.name || "");
      if (body.friends.length) setFriend(body.friends[0].account_id);
    } catch (problem: any) {
      setError(problem.message);
    }
  }, [deckId]);

  useEffect(() => { load(); }, [load]);

  const other = compared?.friends.find((f: any) => f.account_id === friend);

  const rows = useMemo(() => {
    if (!compared || !other) return [];
    const theirs = Object.fromEntries(other.topics.map((t: any) => [t.deck_path, t.mastery]));
    const built = compared.you.topics.map((topic: any) => ({
      path: topic.deck_path,
      you: Math.round(topic.mastery * 100),
      them: Math.round(((theirs[topic.deck_path] as number) || 0) * 100),
    }));
    if (sort === "gap")
      built.sort((a: any, b: any) => {
        // Behind first (that is the studying signal), then your leads,
        // and dead ties last — a list led by 0–0 rows answers nothing.
        const rank = (t: any) => (t.them > t.you ? 0 : t.you > t.them ? 1 : 2);
        return rank(a) - rank(b) || Math.abs(b.you - b.them) - Math.abs(a.you - a.them);
      });
    return built;
  }, [compared, other, sort]);

  const weakest = useMemo(() => {
    if (!compared) return null;
    const sorted = [...compared.you.topics].sort((a: any, b: any) => a.mastery - b.mastery);
    return sorted[0] || null;
  }, [compared]);

  if (error) return (
    <View style={{ flex: 1, backgroundColor: palette.bg, padding: space[3], paddingTop: insets.top + space[3] }}>
      <ErrorCard message={error} onRetry={load} />
    </View>
  );
  if (!compared) return (
    <View style={{ flex: 1, backgroundColor: palette.bg, padding: space[3], paddingTop: insets.top + space[3], gap: space[3] }}>
      <Skeleton h={60} />
      <Skeleton h={200} />
    </View>
  );

  return (
    <View style={{ flex: 1, backgroundColor: palette.bg, paddingTop: insets.top }}>
      <View style={{ flexDirection: "row", alignItems: "center", paddingHorizontal: space[2] }}>
        <IconBtn name="chevL" label="Back" onPress={() => goBack()} />
        <Cap style={{ flex: 1, textAlign: "center" }}>{deckName}</Cap>
        {/* Spacer keeps the title centered with no right action. */}
        <View style={{ width: target.min }} />
      </View>
      <Cap style={{ textAlign: "center" }}>topic by topic, against one friend</Cap>

      <ScrollView style={{ flex: 1 }} contentContainerStyle={{
        padding: space[3], paddingTop: space[3], paddingBottom: insets.bottom + space[4], gap: space[3],
      }}>
        {compared.friends.length === 0 ? (
          <CardBox style={{ padding: space[5], gap: space[3] }}>
            <T v="secondary">{compared.why_empty}</T>
            <Button title="Share this deck" onPress={() => router.push(`/deck/${deckId}`)} />
          </CardBox>
        ) : (
          <>
            <View style={{ flexDirection: "row", gap: space[2] }}>
              {compared.friends.length > 1 && (
                <View style={{ flex: 1 }}>
                  <Seg
                    options={compared.friends.map((f: any): [string, string] => [
                      f.account_id,
                      f.display_name || f.account_id.slice(0, 6),
                    ])}
                    value={friend ?? ""}
                    onChange={setFriend}
                  />
                </View>
              )}
              <View style={{ flex: 1.3 }}>
                <Seg
                  options={[["order", "By order"], ["gap", "Biggest gap"]]}
                  value={sort}
                  onChange={setSort}
                />
              </View>
            </View>

            <View style={{ gap: space[2] }}>
              {rows.map((row: any) => (
                <View key={row.path} style={{
                  backgroundColor: palette.surface, borderColor: palette.border, borderWidth: 1,
                  borderRadius: radius.md, paddingHorizontal: 14, paddingVertical: 12, gap: 8,
                }}>
                  <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
                    <T v="secondary" style={{ fontWeight: "600", flexShrink: 1 }}>
                      {row.path.split("::").pop()}
                    </T>
                    {/* Muted, and only when ahead — the bars already say the rest. */}
                    {row.you > row.them && <Pill text={`+${row.you - row.them}`} />}
                  </View>
                  <BarRow label="You" value={row.you} accent />
                  <BarRow label={other?.display_name?.split(" ")[0] || "Them"} value={row.them} />
                </View>
              ))}
            </View>

            {weakest && (
              <Button title="Study your weakest topic"
                onPress={() => router.push(`/study/${deckId}`)} />
            )}
          </>
        )}
      </ScrollView>
    </View>
  );
}

function BarRow({ label, value, accent }: { label: string; value: number; accent?: boolean }) {
  const palette = usePalette();
  return (
    <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
      <Cap style={{ width: 34 }}>{label}</Cap>
      <View style={{ flex: 1, height: 4, borderRadius: 2, backgroundColor: palette.sunken, overflow: "hidden" }}>
        <View style={{
          width: `${value}%`, height: 4, borderRadius: 2,
          backgroundColor: accent ? palette.accent : palette.borderStrong,
        }} />
      </View>
      <Cap color={accent ? palette.text : palette.text2}
        style={{ width: 26, textAlign: "right", fontWeight: "600", fontVariant: ["tabular-nums"] }}>
        {value}
      </Cap>
    </View>
  );
}
