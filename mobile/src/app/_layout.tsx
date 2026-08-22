// The root: theme, toasts, and the session gate. In development the gate
// is quiet — the app signs itself in against the dev server's published
// token; anywhere else it is the real sign-in screen.
import { Stack } from "expo-router";
import React, { useEffect, useState } from "react";
import { StatusBar, View } from "react-native";
import { loadSession, SessionKind, subscribeSession } from "../lib/session";
import SignIn from "../screens/sign-in";
import { ThemeProvider, usePalette } from "../theme";
import { ToastHost } from "../ui";

function Gate() {
  const palette = usePalette();
  const [kind, setKind] = useState<SessionKind | undefined>(undefined);

  useEffect(() => {
    loadSession().then(setKind);
    return subscribeSession(setKind);
  }, []);

  if (kind === undefined) {
    return <View style={{ flex: 1, backgroundColor: palette.bg }} />;
  }
  if (kind === null) {
    return <SignIn onSignedIn={() => loadSession().then(setKind)} />;
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
