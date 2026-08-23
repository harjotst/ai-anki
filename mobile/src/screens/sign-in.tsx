// The way in. Email and password work everywhere; Google opens the
// provider's own page and comes back by deep link. The development server,
// when one is running, signs the app in by itself before this screen is
// ever seen — so being here means a real account is the only way forward.
import React, { useState } from "react";
import { KeyboardAvoidingView, Platform, ScrollView, TextInput, View } from "react-native";
import { devAvailable, signInWithEmail, signInWithGoogle, signUpWithEmail, useDevData } from "../lib/session";
import { configured } from "../lib/supabase";
import { radius, space, usePalette } from "../theme";
import { Button, Cap, T } from "../ui";

export default function SignIn({ onSignedIn }: { onSignedIn: () => void }) {
  const palette = usePalette();
  const [dev, setDev] = useState(false);
  React.useEffect(() => {
    devAvailable().then(setDev);
  }, []);
  const [mode, setMode] = useState<"in" | "up">("in");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const field = {
    borderWidth: 1, borderColor: palette.border, borderRadius: radius.md,
    paddingHorizontal: space[3], minHeight: 48, color: palette.text,
    fontSize: 16, backgroundColor: palette.surface,
  };

  const run = async (task: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await task();
    } catch (problem: any) {
      setError(problem.message);
    } finally {
      setBusy(false);
    }
  };

  const submit = () =>
    run(async () => {
      if (mode === "in") {
        await signInWithEmail(email.trim(), password);
        onSignedIn();
      } else {
        const ready = await signUpWithEmail(email.trim(), password);
        if (ready) onSignedIn();
        else setNotice("Check your email — the account needs confirming before the first sign-in.");
      }
    });

  const google = () =>
    run(async () => {
      await signInWithGoogle();
      onSignedIn();
    });

  return (
    <KeyboardAvoidingView
      style={{ flex: 1, backgroundColor: palette.bg }}
      behavior={Platform.OS === "ios" ? "padding" : undefined}
    >
      <ScrollView
        contentContainerStyle={{ flexGrow: 1, justifyContent: "center", padding: space[4], gap: space[3] }}
        keyboardShouldPersistTaps="handled"
      >
        <T v="display">ai-anki</T>
        <T v="secondary" style={{ marginBottom: space[2] }}>
          Study a little every day. Sign in and your decks, streak and friends
          are on every device you own.
        </T>

        {configured ? (
          <>
            <TextInput
              style={field} placeholder="Email" placeholderTextColor={palette.muted}
              autoCapitalize="none" autoComplete="email" keyboardType="email-address"
              value={email} onChangeText={setEmail}
            />
            <TextInput
              style={field} placeholder="Password" placeholderTextColor={palette.muted}
              secureTextEntry autoComplete={mode === "in" ? "current-password" : "new-password"}
              value={password} onChangeText={setPassword} onSubmitEditing={submit}
            />
            {error && <T v="secondary" color={palette.danger}>{error}</T>}
            {notice && <T v="secondary" color={palette.accent}>{notice}</T>}
            <Button
              title={mode === "in" ? "Sign in" : "Create account"}
              onPress={submit}
              disabled={busy || !email.trim() || !password}
            />
            <Button
              title={mode === "in" ? "New here? Create an account" : "Have an account? Sign in"}
              kind="ghost"
              onPress={() => { setMode(mode === "in" ? "up" : "in"); setError(null); setNotice(null); }}
            />
            <View style={{ flexDirection: "row", alignItems: "center", gap: space[3], marginVertical: space[1] }}>
              <View style={{ flex: 1, height: 1, backgroundColor: palette.border }} />
              <Cap>or</Cap>
              <View style={{ flex: 1, height: 1, backgroundColor: palette.border }} />
            </View>
            <Button title="Continue with Google" kind="ghost" onPress={google} disabled={busy} />
            {dev && (
              <Button title="Use local dev data" kind="ghost"
                onPress={() => run(async () => { if (await useDevData()) onSignedIn(); })} />
            )}
          </>
        ) : (
          <Cap>
            This build has no sign-in configured and no local development
            server answered. Start one, then try again from You → Sign out.
          </Cap>
        )}
      </ScrollView>
    </KeyboardAvoidingView>
  );
}
