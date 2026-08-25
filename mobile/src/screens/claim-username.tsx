// The first thing a new account does: pick the name friends will type.
// One field, one rule set, skippable — nobody is locked out of studying
// over a handle.
import React, { useState } from "react";
import { KeyboardAvoidingView, Platform, ScrollView, TextInput } from "react-native";
import { api } from "../lib/session";
import { radius, space, usePalette } from "../theme";
import { Button, Cap, T } from "../ui";

export default function ClaimUsername({ onDone }: { onDone: () => void }) {
  const palette = usePalette();
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const claim = async () => {
    setBusy(true);
    setError(null);
    try {
      await api("/api/me", {
        method: "PATCH",
        body: JSON.stringify({ username: name.trim().replace(/^@/, "") }),
      });
      onDone();
    } catch (problem: any) {
      setError(problem.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <KeyboardAvoidingView
      style={{ flex: 1, backgroundColor: palette.bg }}
      behavior={Platform.OS === "ios" ? "padding" : undefined}
    >
      <ScrollView
        contentContainerStyle={{ flexGrow: 1, justifyContent: "center", padding: space[4], gap: space[3] }}
        keyboardShouldPersistTaps="handled"
      >
        <T v="title">Pick a username</T>
        <T v="secondary">
          It's how friends add you — no codes to copy around. Letters,
          numbers and underscores; 3 to 20 of them.
        </T>
        <TextInput
          style={{
            borderWidth: 1, borderColor: palette.border, borderRadius: radius.md,
            paddingHorizontal: space[3], minHeight: 48, color: palette.text,
            fontSize: 16, backgroundColor: palette.surface,
          }}
          placeholder="username"
          placeholderTextColor={palette.muted}
          autoCapitalize="none"
          autoCorrect={false}
          value={name}
          onChangeText={setName}
          onSubmitEditing={claim}
        />
        {error && <T v="secondary" color={palette.danger}>{error}</T>}
        <Button title="Claim it" onPress={claim} disabled={busy || name.trim().length < 3} />
        <Button title="Later" kind="ghost" onPress={onDone} />
        <Cap>You can change it any time under You.</Cap>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}
