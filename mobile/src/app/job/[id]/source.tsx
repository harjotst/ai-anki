// The document a deck was made from, full screen. Downloaded with the
// person's credentials into the cache, then shown by the system's own PDF
// renderer through a WebView — scrolling and pinch-zoom come with it. A
// purged upload (410) says so in words instead of opening a blank reader.
import * as FileSystem from "expo-file-system/legacy";
import * as Sharing from "expo-sharing";
import { useLocalSearchParams } from "expo-router";
import React, { useCallback, useEffect, useState } from "react";
import { View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { WebView } from "react-native-webview";
import { useGoBack } from "../../../lib/nav";
import { authHeaders, BASE } from "../../../lib/session";
import { space, usePalette } from "../../../theme";
import { Cap, ErrorCard, IconBtn, Skeleton } from "../../../ui";

export default function SourceDocument() {
  const { id, name } = useLocalSearchParams<{ id: string; name?: string }>();
  const goBack = useGoBack();
  const palette = usePalette();
  const insets = useSafeAreaInsets();
  const [uri, setUri] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      // The cache copy keeps the job id in its name, so two decks' documents
      // with the same filename never overwrite each other.
      const extension = (name || "").match(/\.(pdf|txt|md)$/i)?.[0] || ".pdf";
      const result = await FileSystem.downloadAsync(
        `${BASE}/api/jobs/${id}/source`,
        `${FileSystem.cacheDirectory}source-${id}${extension.toLowerCase()}`,
        { headers: (await authHeaders()) as Record<string, string> },
      );
      if (result.status !== 200) {
        await FileSystem.deleteAsync(result.uri, { idempotent: true }).catch(() => {});
        throw new Error(result.status === 410
          ? "The original file isn't stored anymore, so it can't be opened."
          : `Couldn't open the document (${result.status}).`);
      }
      setUri(result.uri);
    } catch (problem: any) {
      setError(problem.message);
    }
  }, [id, name]);

  useEffect(() => { load(); }, [load]);

  return (
    <View style={{ flex: 1, backgroundColor: palette.bg, paddingTop: insets.top }}>
      <View style={{ flexDirection: "row", alignItems: "center", paddingHorizontal: space[2] }}>
        <IconBtn name="chevL" label="Back" onPress={() => goBack()} />
        <Cap style={{ flex: 1, textAlign: "center" }}>{name || "Document"}</Cap>
        <IconBtn name="download" label="Share" onPress={() => uri && Sharing.shareAsync(uri)} />
      </View>
      {error ? (
        <View style={{ padding: space[3] }}><ErrorCard message={error} onRetry={load} /></View>
      ) : !uri ? (
        <View style={{ padding: space[3] }}><Skeleton h={400} /></View>
      ) : (
        <WebView
          source={{ uri }}
          originWhitelist={["*"]}
          allowingReadAccessToURL={FileSystem.cacheDirectory ?? undefined}
          style={{ flex: 1, backgroundColor: palette.bg }}
        />
      )}
    </View>
  );
}
