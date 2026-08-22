// You: theme, who you are, and the way out. A native mirror of the web
// screen, minus identity linking — connecting and disconnecting sign-in
// methods stays on the web until native auth lands.
import { useRouter } from "expo-router";
import React, { useCallback, useEffect, useState } from "react";
import { View } from "react-native";
import { cached } from "../../lib/data";
import { signOut } from "../../lib/session";
import { space, type ThemeSetting, useThemeSetting } from "../../theme";
import { Button, Cap, CardBox, ErrorCard, Screen, Seg, Skeleton, T } from "../../ui";

export default function You() {
  const router = useRouter();
  const { setting, setSetting } = useThemeSetting();
  const [me, setMe] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setMe(await cached("/api/me", 300_000));
    } catch (problem: any) {
      setError(problem.message);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const body = () => {
    if (error) return <ErrorCard message={error} onRetry={load} />;
    if (!me) return <><Skeleton h={60} /><Skeleton h={120} /></>;

    return (
      <>
        <T v="title">You</T>

        <CardBox>
          <T v="heading">{me.display_name || me.email}</T>
          {me.display_name ? <Cap>{me.email}</Cap> : null}
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
          Sign-in methods are managed on the web.
        </Cap>

        <Button title="Sign out" kind="ghost" onPress={async () => {
          await signOut();
          router.replace("/");
        }} />
      </>
    );
  };

  return <Screen>{body()}</Screen>;
}
