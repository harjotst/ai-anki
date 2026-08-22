// The upload screen, phone side: pick lecture files, choose the deck they
// feed, hand them to the pipeline. Mirrors the web's /job/new — same field
// names, same copy — with the file input swapped for the system picker.
import * as DocumentPicker from "expo-document-picker";
import { useLocalSearchParams, useRouter } from "expo-router";
import React, { useEffect, useRef, useState } from "react";
import { Pressable, ScrollView, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { cached, dropCache } from "../../lib/data";
import { api, upload } from "../../lib/session";
import { radius, space, target, usePalette } from "../../theme";
import { Button, Cap, ErrorCard, Icon, IconBtn, Sheet, T } from "../../ui";

export default function NewJob() {
  const router = useRouter();
  const palette = usePalette();
  const insets = useSafeAreaInsets();
  const { deck } = useLocalSearchParams<{ deck?: string }>();

  const [decks, setDecks] = useState<any[]>([]);
  const [deckId, setDeckId] = useState(typeof deck === "string" ? deck : "");
  const [files, setFiles] = useState<DocumentPicker.DocumentPickerAsset[]>([]);
  const [choosing, setChoosing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Jobs already created from this batch, so a retry after a mid-batch
  // failure resumes instead of duplicating the files that got through.
  const created = useRef(new Map<string, string>());
  const planFired = useRef(new Set<string>());

  useEffect(() => {
    cached("/api/decks", 60_000)
      .then((body) => setDecks(body.decks.filter((d: any) => !d.shared_with_me)))
      .catch(() => {});
  }, []);

  const pick = async () => {
    const result = await DocumentPicker.getDocumentAsync({
      multiple: true,
      copyToCacheDirectory: true,
    });
    if (result.canceled) return;
    // A fresh pick is a fresh batch — the native mirror of the web clearing
    // its input after a failure so the same file can be chosen again.
    created.current.clear();
    planFired.current.clear();
    setFiles(result.assets);
    setError(null);
  };

  const send = async () => {
    if (!files.length) return;
    setBusy(true);
    setError(null);
    try {
      // POST /api/jobs takes exactly one file, so each picked file becomes
      // its own job — all into the same deck: the first upload founds it
      // when none was chosen, the rest continue it.
      let targetDeck = deckId;
      let firstJobId: string | null = null;
      for (const file of files) {
        let jobId = created.current.get(file.uri);
        if (!jobId) {
          const body = new FormData();
          body.append("file", {
            uri: file.uri,
            name: file.name,
            type: file.mimeType || "application/octet-stream",
          } as any);
          if (targetDeck) body.append("deck_id", targetDeck);
          const { job_id } = await upload("/api/jobs", body);
          jobId = job_id as string;
          created.current.set(file.uri, jobId);
        }
        if (!firstJobId) {
          firstJobId = jobId;
          if (!targetDeck && files.length > 1) {
            targetDeck = (await api(`/api/jobs/${jobId}`)).deck_id;
          }
        } else if (!planFired.current.has(jobId)) {
          // The job screen auto-plans only the job it shows. Kick the rest
          // off here so they surface on Today as "plan ready" instead of
          // sitting in "uploaded", a state no mobile screen resumes from.
          // A duplicate fire is refused by the server (409), never re-run.
          planFired.current.add(jobId);
          api(`/api/jobs/${jobId}/plan`, { method: "POST" }).catch(() => {});
        }
      }
      dropCache("/api/jobs");
      router.replace(`/job/${firstJobId}`);
    } catch (problem: any) {
      setError(problem.message);
      setBusy(false);
    }
  };

  const chosen = decks.find((d) => d.deck_id === deckId);

  const fieldRow = {
    flexDirection: "row" as const,
    alignItems: "center" as const,
    gap: space[2],
    minHeight: target.min,
    borderWidth: 1,
    borderColor: palette.border,
    borderRadius: radius.md,
    backgroundColor: palette.surface,
    paddingHorizontal: 14,
  };

  return (
    <View style={{ flex: 1, backgroundColor: palette.bg, paddingTop: insets.top }}>
      <View style={{ flexDirection: "row", alignItems: "center", paddingHorizontal: space[2] }}>
        <IconBtn name="chevL" label="Back" onPress={() => router.back()} />
        <Cap style={{ flex: 1, textAlign: "center" }}>Add a lecture</Cap>
        <View style={{ width: target.min }} />
      </View>

      <ScrollView
        style={{ flex: 1 }}
        contentContainerStyle={{ padding: space[3], gap: space[3], paddingBottom: insets.bottom + space[5] }}
        keyboardShouldPersistTaps="handled"
      >
        <View style={{ gap: space[1] }}>
          <Cap style={{ paddingLeft: 2 }}>Into</Cap>
          <Pressable
            onPress={() => setChoosing(true)}
            style={({ pressed }) => [fieldRow, { backgroundColor: pressed ? palette.sunken : palette.surface }]}
          >
            <T v="body" numberOfLines={1} style={{ flex: 1, fontWeight: "600" }}>
              {deckId ? (chosen ? `${chosen.name} (${chosen.card_count} cards)` : "…") : "A new deck"}
            </T>
            <Icon name="chevD" size={16} color={palette.muted} />
          </Pressable>
          {deckId !== "" && (
            <Cap>
              Cards that improve on ones already here update them in place
              rather than arriving alongside them.
            </Cap>
          )}
        </View>

        <Pressable
          onPress={pick}
          style={({ pressed }) => ({
            alignItems: "center" as const, gap: space[1],
            paddingVertical: space[5], paddingHorizontal: space[4],
            borderWidth: 1.5, borderStyle: "dashed" as const,
            borderColor: palette.borderStrong, borderRadius: radius.lg,
            backgroundColor: pressed ? palette.sunken : "transparent",
          })}
        >
          <Icon name="doc" size={28} />
          <T v="secondary">Browse for a lecture</T>
          <Cap style={{ textAlign: "center" }}>
            PDF, Word, PowerPoint, Excel, text or images — scans are fine
          </Cap>
        </Pressable>

        {files.map((file) => (
          <View key={file.uri} style={[fieldRow, { paddingRight: 0 }]}>
            <T v="body" numberOfLines={1} style={{ flex: 1, fontWeight: "600" }}>{file.name}</T>
            {file.size != null && (
              <Cap style={{ fontVariant: ["tabular-nums"] }}>
                {(file.size / 1024 / 1024).toFixed(1)} MB
              </Cap>
            )}
            <IconBtn name="x" label="Remove file"
              onPress={() => setFiles((current) => current.filter((f) => f.uri !== file.uri))} />
          </View>
        ))}

        {error && <ErrorCard message={error} onRetry={send} />}
        <Button title={busy ? "Uploading…" : "Upload & plan"} onPress={send}
          disabled={!files.length || busy} />
      </ScrollView>

      {choosing && (
        <Sheet onClose={() => setChoosing(false)}>
          <T v="heading">Into</T>
          <ScrollView style={{ maxHeight: 400 }}>
            <DeckRow label="A new deck" selected={deckId === ""}
              onPress={() => { setDeckId(""); setChoosing(false); }} />
            {decks.map((d) => (
              <DeckRow key={d.deck_id} label={d.name} caption={`${d.card_count} cards`}
                selected={d.deck_id === deckId}
                onPress={() => { setDeckId(d.deck_id); setChoosing(false); }} />
            ))}
          </ScrollView>
        </Sheet>
      )}
    </View>
  );
}

function DeckRow({ label, caption, selected, onPress }: {
  label: string; caption?: string; selected: boolean; onPress: () => void;
}) {
  const palette = usePalette();
  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => ({
        flexDirection: "row" as const, alignItems: "center" as const, gap: space[3],
        minHeight: target.min, paddingHorizontal: space[1], borderRadius: radius.sm,
        backgroundColor: pressed ? palette.sunken : "transparent",
      })}
    >
      <View style={{ flex: 1 }}>
        <T v="body" numberOfLines={1} style={{ fontWeight: selected ? "600" : "400" }}>{label}</T>
        {caption ? <Cap>{caption}</Cap> : null}
      </View>
      {selected && <Icon name="check" size={18} color={palette.accent} />}
    </Pressable>
  );
}
