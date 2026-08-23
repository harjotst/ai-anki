// You: theme, who you are, and the way out. A native mirror of the web
// screen, minus identity linking — connecting and disconnecting sign-in
// methods stays on the web until native auth lands.
import { useRouter } from "expo-router";
import React, { useCallback, useEffect, useState } from "react";
import { TextInput, View } from "react-native";
import { cached, dropCache } from "../../lib/data";
import { api, sessionKind, signOut } from "../../lib/session";
import { radius, space, type ThemeSetting, usePalette, useThemeSetting } from "../../theme";
import { Button, Cap, CardBox, ErrorCard, Screen, Seg, Sheet, Skeleton, T, useToast } from "../../ui";

export default function You() {
  const router = useRouter();
  const toast = useToast();
  const { setting, setSetting } = useThemeSetting();
  const [me, setMe] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      setMe(await cached("/api/me", 300_000));
    } catch (problem: any) {
      setError(problem.message);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const saved = () => {
    setEditing(false);
    // The name travels: friends and leaderboard rows carry it too, so a
    // change here must not leave stale copies in their caches.
    dropCache("/api/me");
    dropCache("/api/friends");
    dropCache("/api/leaderboard");
    toast("Saved");
    load();
  };

  const body = () => {
    if (error) return <ErrorCard message={error} onRetry={load} />;
    if (!me) return <><Skeleton h={60} /><Skeleton h={120} /></>;

    return (
      <>
        <T v="title">You</T>

        <CardBox>
          <View style={{ flexDirection: "row", alignItems: "center", gap: space[3] }}>
            <View style={{ flex: 1, gap: 2 }}>
              <T v="heading">{me.display_name || me.email}</T>
              <T v="secondary">{me.username ? `@${me.username}` : "No username yet"}</T>
              {me.display_name ? <Cap>{me.email}</Cap> : null}
            </View>
            <Button title="Edit" kind="ghost" onPress={() => setEditing(true)} />
          </View>
        </CardBox>

        <View style={{ gap: space[1] }}>
          <Cap style={{ paddingLeft: 2 }}>Appearance</Cap>
          <Seg
            options={[["system", "System"], ["light", "Light"], ["dark", "Dark"]]}
            value={setting}
            onChange={(next) => setSetting(next as ThemeSetting)}
          />
        </View>

        <Cap style={{ paddingLeft: 2 }}>
          {sessionKind() === "dev"
            ? "Signed in through the local development server. Sign out to reach the real sign-in screen."
            : "Connecting extra sign-in methods is managed on the web."}
        </Cap>

        <Button title="Sign out" kind="ghost" onPress={async () => {
          await signOut();
          router.replace("/");
        }} />
      </>
    );
  };

  return (
    <Screen>
      {body()}
      {editing && me && (
        <EditIdentitySheet me={me} onClose={() => setEditing(false)} onSaved={saved} />
      )}
    </Screen>
  );
}

function EditIdentitySheet({ me, onClose, onSaved }: {
  me: any; onClose: () => void; onSaved: () => void;
}) {
  const palette = usePalette();
  const [displayName, setDisplayName] = useState<string>(me.display_name ?? "");
  const [username, setUsername] = useState<string>(me.username ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const field = {
    borderWidth: 1, borderColor: palette.border, borderRadius: radius.md,
    paddingHorizontal: space[3], minHeight: 48, color: palette.text,
    fontSize: 16, backgroundColor: palette.bg,
  };

  const save = async () => {
    // Send only what changed. An untouched empty username field means
    // "leave it be" — the server reads "" as a claim, and rejects it.
    const handle = username.trim().replace(/^@/, "");
    const body: any = {};
    if (displayName.trim() !== (me.display_name ?? "")) body.display_name = displayName.trim();
    if (handle && handle !== (me.username ?? "")) body.username = handle;
    if (!Object.keys(body).length) { onClose(); return; }
    setBusy(true);
    setError(null);
    try {
      await api("/api/me", { method: "PATCH", body: JSON.stringify(body) });
      onSaved();
    } catch (problem: any) {
      // 409 "that username is taken" and the 422 rule both arrive as detail.
      setError(problem.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Sheet onClose={onClose}>
      <T v="heading">Edit profile</T>
      <View style={{ gap: space[1] }}>
        <Cap style={{ paddingLeft: 2 }}>Display name</Cap>
        <TextInput
          style={field}
          value={displayName}
          onChangeText={setDisplayName}
          placeholder="Your name"
          placeholderTextColor={palette.muted}
        />
      </View>
      <View style={{ gap: space[1] }}>
        <Cap style={{ paddingLeft: 2 }}>Username</Cap>
        <TextInput
          style={field}
          value={username}
          onChangeText={setUsername}
          placeholder="username"
          placeholderTextColor={palette.muted}
          autoCapitalize="none"
          autoCorrect={false}
        />
        <Cap style={{ paddingLeft: 2 }}>
          Letters, numbers and underscores; 3 to 20 of them.
        </Cap>
      </View>
      {error && <T v="secondary" color={palette.danger}>{error}</T>}
      <View style={{ flexDirection: "row", gap: space[2] }}>
        <Button title="Cancel" kind="ghost" style={{ flex: 1 }} onPress={onClose} />
        <Button title="Save" style={{ flex: 1 }} onPress={save} disabled={busy} />
      </View>
    </Sheet>
  );
}
