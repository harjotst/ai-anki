// The review queue: the reason a rating never waits on the network.
// A straight port of the web's queue.js onto AsyncStorage, with the same
// contract: append, advance the UI immediately, flush idempotent batches.
import AsyncStorage from "@react-native-async-storage/async-storage";
import { AppState } from "react-native";
import { api } from "./session";

export const uuid = (): string =>
  (globalThis as any).crypto?.randomUUID
    ? (globalThis as any).crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;

export type QueuedReview = {
  client_uuid: string;
  card_uuid: string;
  rating: string;
  reviewed_at: string;
  duration_ms?: number;
};

const KEY = "ai_anki_review_queue";
let rows: QueuedReview[] = [];
let loaded = false;

async function ensureLoaded() {
  if (loaded) return;
  try {
    rows = JSON.parse((await AsyncStorage.getItem(KEY)) || "[]");
  } catch {
    rows = [];
  }
  loaded = true;
}

const persist = () => AsyncStorage.setItem(KEY, JSON.stringify(rows));

const listeners = new Set<(count: number) => void>();
const notify = () => listeners.forEach((fn) => fn(rows.length));

export function pendingCount() {
  return rows.length;
}

export function subscribe(fn: (count: number) => void) {
  listeners.add(fn);
  return () => void listeners.delete(fn);
}

export async function enqueue(review: QueuedReview) {
  await ensureLoaded();
  rows = [...rows, review];
  await persist();
  notify();
  void flush();
}

/** Undo support: remove a review that has not been flushed yet. Returns
 *  whether it was still here — if not, it already reached the server and
 *  the undo becomes a superseding review instead of a retraction. */
export async function removeQueued(clientUuid: string) {
  await ensureLoaded();
  const kept = rows.filter((row) => row.client_uuid !== clientUuid);
  if (kept.length === rows.length) return false;
  rows = kept;
  await persist();
  notify();
  return true;
}

let flushing = false;

export async function flush() {
  if (flushing) return;
  await ensureLoaded();
  const batch = rows.slice();
  if (!batch.length) return;
  flushing = true;
  try {
    await api("/api/reviews", {
      method: "POST",
      body: JSON.stringify({ reviews: batch }),
    });
    // Only drop what was sent; anything enqueued during the flight stays.
    rows = rows.slice(batch.length);
    await persist();
  } catch {
    // Still queued; the next trigger retries. The sync pill in the study
    // screen is the honest surface for this state.
  } finally {
    flushing = false;
    notify();
  }
}

// Returning to the app is the phone's "reconnected": retry then.
AppState.addEventListener("change", (state) => {
  if (state === "active") void flush();
});
