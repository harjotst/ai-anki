// The root: theme, toasts, and the session gate. The gate is quiet in
// development — the app signs itself in against the dev server's published
// token — and becomes the real sign-in screen when native auth lands.
import { Stack } from "expo-router";
import React, { useEffect, useState } from "react";
import { StatusBar, View } from "react-native";
import { loadSession } from "../lib/session";
import { ThemeProvider, usePalette } from "../theme";
import { Button, Screen, T, ToastHost } from "../ui";

function Gate() {
  const palette = usePalette();
  const [signedIn, setSignedIn] = useState<boolean | undefined>(undefined);

  const establish = () => loadSession().then(setSignedIn);
  useEffect(() => { establish(); }, []);

  if (signedIn === undefined) {
    return <View style={{ flex: 1, backgroundColor: palette.bg }} />;
  }
  if (!signedIn) {
    return (
      <Screen style={{ justifyContent: "center", flexGrow: 1 }}>
        <T v="display">ai-anki</T>
        <T v="secondary">
          Sign in to continue. This development build signs in automatically
          when the local server is running.
        </T>
        <Button title="Try again" onPress={establish} />
      </Screen>
    );
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
