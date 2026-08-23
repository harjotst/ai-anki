// The root: theme, toasts, and the session gate. A real session beats the
// dev bypass, an explicit sign-out sticks, and a fresh account picks its
// public handle before it meets the tabs.
import { Stack } from "expo-router";
import React, { useCallback, useEffect, useState } from "react";
import { StatusBar, View } from "react-native";
import { api, loadSession, SessionKind, subscribeSession } from "../lib/session";
import ClaimUsername from "../screens/claim-username";
import SignIn from "../screens/sign-in";
import { ThemeProvider, usePalette } from "../theme";
import { ToastHost } from "../ui";

function Gate() {
  const palette = usePalette();
  const [kind, setKind] = useState<SessionKind | undefined>(undefined);
  const [needsName, setNeedsName] = useState<boolean | undefined>(undefined);

  const check = useCallback(async (next: SessionKind) => {
    setKind(next);
    if (!next) return setNeedsName(undefined);
    try {
      const me = await api("/api/me");
      setNeedsName(!me.username);
    } catch {
      setNeedsName(false); // the tabs surface API trouble better than a gate
    }
  }, []);

  useEffect(() => {
    loadSession().then(check);
    return subscribeSession(check);
  }, [check]);

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
