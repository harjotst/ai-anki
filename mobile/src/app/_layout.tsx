// The root: theme, toasts, and the session gate. A real session beats the
// dev bypass, an explicit sign-out sticks, and a fresh account picks its
// public handle before it meets the tabs.
import { Stack } from "expo-router";
import React, { useCallback, useEffect, useState } from "react";
import { StatusBar, View } from "react-native";
import { api, loadSession, SessionKind, signOut, subscribeSession } from "../lib/session";
import ClaimUsername from "../screens/claim-username";
import SignIn from "../screens/sign-in";
import { ThemeProvider, usePalette } from "../theme";
import { Button, Screen, T, ToastHost } from "../ui";

function Gate() {
  const palette = usePalette();
  const [kind, setKind] = useState<SessionKind | undefined>(undefined);
  const [needsName, setNeedsName] = useState<boolean | undefined>(undefined);
  const [denied, setDenied] = useState(false);

  const check = useCallback(async (next: SessionKind) => {
    setKind(next);
    setDenied(false);
    if (!next) return setNeedsName(undefined);
    try {
      const me = await api("/api/me");
      setNeedsName(!me.username);
    } catch (problem: any) {
      // A private build said no. That is a state with one exit, not an
      // error the tabs can do anything with.
      if (problem?.status === 403) return setDenied(true);
      setNeedsName(false); // other API trouble surfaces better in the tabs
    }
  }, []);

  useEffect(() => {
    loadSession().then(check);
    return subscribeSession(check);
  }, [check]);

  // Denied outranks loading: the denied path never resolves needsName, so
  // checking the loading guard first would blank the screen forever.
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
  if (kind === undefined || (kind && needsName === undefined)) {
    return <View style={{ flex: 1, backgroundColor: palette.bg }} />;
  }
  if (kind === null) {
    return <SignIn onSignedIn={() => loadSession().then(check)} />;
  }
  if (needsName) {
    return <ClaimUsername onDone={() => setNeedsName(false)} />;
  }
  return (
    <Stack screenOptions={{ headerShown: false }}>
      <Stack.Screen name="(tabs)" />
      <Stack.Screen name="study/[deckId]" options={{ gestureEnabled: false }} />
    </Stack>
  );
}

export default function RootLayout() {
  return (
    <ThemeProvider>
      <ToastHost>
        <StatusBar barStyle="default" />
        <Gate />
      </ToastHost>
    </ThemeProvider>
  );
}
