// The root: toasts and the session gate. A real session beats the dev
// bypass, and an explicit sign-out sticks. Signed in, the app is one page
// (index) with full-screen screens pushed over it.
import { Stack } from "expo-router";
import React, { useCallback, useEffect, useState } from "react";
import { StatusBar, View } from "react-native";
import { api, loadSession, SessionKind, signOut, subscribeSession } from "../lib/session";
import SignIn from "../screens/sign-in";
import { usePalette } from "../theme";
import { Button, Screen, T, ToastHost } from "../ui";

function Gate() {
  const palette = usePalette();
  const [kind, setKind] = useState<SessionKind | undefined>(undefined);
  const [denied, setDenied] = useState(false);

  const check = useCallback(async (next: SessionKind) => {
    setDenied(false);
    if (next) {
      try {
        await api("/api/me");
      } catch (problem: any) {
        // A private build said no. That is a state with one exit, not an
        // error the home page can do anything with.
        if (problem?.status === 403) setDenied(true);
        // Other API trouble surfaces better on the page itself.
      }
    }
    setKind(next);
  }, []);

  useEffect(() => {
    loadSession().then(check);
    return subscribeSession(check);
  }, [check]);

  if (denied) {
    return (
      <Screen style={{ justifyContent: "center", flexGrow: 1 }}>
        <T v="display">Private build</T>
        <T v="secondary">
          This copy of ai-anki belongs to specific people, and the account
          you signed in with isn't one of them.
        </T>
        <Button title="Sign out" kind="ghost"
          onPress={() => signOut().then(() => loadSession().then(check))} />
      </Screen>
    );
  }
  if (kind === undefined) {
    return <View style={{ flex: 1, backgroundColor: palette.bg }} />;
  }
  if (kind === null) {
    return <SignIn onSignedIn={() => loadSession().then(check)} />;
  }
  return (
    <Stack screenOptions={{ headerShown: false }}>
      <Stack.Screen name="index" />
      <Stack.Screen name="study/[deckId]" options={{ gestureEnabled: false }} />
    </Stack>
  );
}

export default function RootLayout() {
  return (
    <ToastHost>
      <StatusBar barStyle="default" />
      <Gate />
    </ToastHost>
  );
}
