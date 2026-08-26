// The way in: Google or Apple, nothing else. Each button wears its owner's
// brand — Apple's is the system-drawn native control, Google's follows the
// published spec — because a sign-in button people don't recognise is a
// sign-in button people don't trust. The development server, when one is
// running, signs the app in by itself before this screen is ever seen.
import * as AppleAuthentication from "expo-apple-authentication";
import React, { useEffect, useState } from "react";
import { Pressable, ScrollView, Text, useColorScheme, View } from "react-native";
import Svg, { Path } from "react-native-svg";
import {
  devAvailable, signInWithApple, signInWithGoogle, useDevData,
} from "../lib/session";
import { configured } from "../lib/supabase";
import { radius, space, target, tokens, usePalette } from "../theme";
import { Button, T } from "../ui";
import { Mascot } from "../ui/mascot";

function GoogleG({ size = 20 }: { size?: number }) {
  const brand = tokens.brand;
  return (
    <Svg width={size} height={size} viewBox="0 0 48 48">
      <Path fill={brand.googleBlue} d="M45.1 24.5c0-1.6-.1-3.1-.4-4.5H24v8.5h11.8c-.5 2.8-2.1 5.1-4.4 6.7v5.5h7.1c4.2-3.9 6.6-9.6 6.6-16.2z" />
      <Path fill={brand.googleGreen} d="M24 46c6 0 11-2 14.6-5.3l-7.1-5.5c-2 1.3-4.5 2.1-7.5 2.1-5.8 0-10.7-3.9-12.4-9.2H4.2v5.7C7.8 40.9 15.3 46 24 46z" />
      <Path fill={brand.googleYellow} d="M11.6 28.1c-.4-1.3-.7-2.7-.7-4.1s.2-2.8.7-4.1v-5.7H4.2C2.8 17.1 2 20.4 2 24s.8 6.9 2.2 9.8l7.4-5.7z" />
      <Path fill={brand.googleRed} d="M24 10.8c3.3 0 6.2 1.1 8.5 3.3l6.3-6.3C35 4.3 30 2 24 2 15.3 2 7.8 7.1 4.2 14.2l7.4 5.7c1.7-5.3 6.6-9.1 12.4-9.1z" />
    </Svg>
  );
}

export default function SignIn({ onSignedIn }: { onSignedIn: () => void }) {
  const palette = usePalette();
  const scheme = useColorScheme();
  const [dev, setDev] = useState(false);
  const [appleReady, setAppleReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const check = () => devAvailable().then((ok) => alive && setDev(ok));
    check();
    const timer = setInterval(check, 3000);
    AppleAuthentication.isAvailableAsync()
      .then((ok) => alive && setAppleReady(ok))
      .catch(() => {});
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, []);

  const run = (task: () => Promise<void>) => async () => {
    setBusy(true);
    setError(null);
    try {
      await task();
      onSignedIn();
    } catch (problem: any) {
      // The person closing the sheet is a decision, not a failure.
      if (problem?.code !== "ERR_REQUEST_CANCELED") setError(problem.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <ScrollView
      style={{ flex: 1, backgroundColor: palette.bg }}
      contentContainerStyle={{ flexGrow: 1, justifyContent: "center", padding: space[4], gap: space[3] }}
    >
      <Mascot size={132} />
      <T v="display" style={{ marginTop: 8 }}>ai-anki</T>
      <T v="secondary" style={{ marginBottom: space[3] }}>
        Study a little every day. Sign in and your decks, streak and friends
        are on every device you own.
      </T>

      {configured && (
        <>
          <Pressable
            onPress={run(signInWithGoogle)}
            disabled={busy}
            style={({ pressed }) => ({
              minHeight: target.rating,
              borderRadius: radius.md,
              borderWidth: 1,
              borderColor: palette.borderStrong,
              backgroundColor: palette.surface,
              flexDirection: "row",
              alignItems: "center",
              justifyContent: "center",
              gap: space[2],
              opacity: busy ? 0.5 : pressed ? 0.8 : 1,
            })}
          >
            <GoogleG />
            <Text style={{ fontSize: 17, fontWeight: "600", color: palette.text }}>
              Continue with Google
            </Text>
          </Pressable>

          {appleReady && (
            <AppleAuthentication.AppleAuthenticationButton
              buttonType={AppleAuthentication.AppleAuthenticationButtonType.CONTINUE}
              buttonStyle={
                scheme === "dark"
                  ? AppleAuthentication.AppleAuthenticationButtonStyle.WHITE
                  : AppleAuthentication.AppleAuthenticationButtonStyle.BLACK
              }
              cornerRadius={radius.md}
              style={{ height: target.rating }}
              onPress={run(signInWithApple)}
            />
          )}

          {error && <T v="secondary" color={palette.danger}>{error}</T>}
        </>
      )}

      {!configured && !dev && (
        <T v="secondary">
          This build has no sign-in configured and no local development
          server has answered yet. Start one and this screen will notice.
        </T>
      )}
      {dev && (
        <Button title="Use local dev data" kind="ghost"
          onPress={run(async () => { if (!(await useDevData())) throw new Error("The dev server stopped answering."); })} />
      )}
      <View style={{ height: space[5] }} />
    </ScrollView>
  );
}
