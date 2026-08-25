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
 *  whether it was still here — if not, it already reached (or is on its
 *  way to) the server, and the undo becomes a superseding review instead
 *  of a retraction. In-flight counts as sent: the POST may already have
 *  landed, and claiming a clean retraction for it loses the re-rating. */
export async function removeQueued(clientUuid: string) {
  await ensureLoaded();
  if (inFlight.has(clientUuid)) return false;
  const kept = rows.filter((row) => row.client_uuid !== clientUuid);
  if (kept.length === rows.length) return false;
  rows = kept;
  await persist();
  notify();
  return true;
}

let flushing = false;
let inFlight = new Set<string>();

async function dropByIdentity(uuids: Iterable<string>) {
  // By identity, never by count: rows can be added or undone during the
  // flight, and slicing a changed array from the head drops the wrong ones.
  const gone = new Set(uuids);
  rows = rows.filter((row) => !gone.has(row.client_uuid));
  await persist();
}

export async function flush(): Promise<void> {
  if (flushing) return;
  await ensureLoaded();
  const batch = rows.slice();
  if (!batch.length) return;
  flushing = true;
  inFlight = new Set(batch.map((row) => row.client_uuid));
  try {
    const reply = await api("/api/reviews", {
      method: "POST",
      body: JSON.stringify({ reviews: batch }),
    });
    await dropByIdentity(inFlight);
    // The server names reviews it skipped (card gone — deck unshared,
    // card rejected). They are gone from the queue with the rest: retrying
    // them would jam everything behind rows that can never land.
    void reply;
  } catch (problem: any) {
    if (problem?.status >= 400 && problem.status < 500) {
      // A 4xx will fail identically forever. Dropping the batch loses
      // these reviews; keeping it loses every review after them, forever.
      await dropByIdentity(inFlight);
    }
    // Anything else (network, 5xx) stays queued; the next trigger retries,
    // and the sync pill is the honest surface for that state.
  } finally {
    flushing = false;
    inFlight = new Set();
    notify();
    // Anything enqueued during the flight goes now, not at some future
    // trigger that may never come.
    if (rows.length) void flush();
  }
}

// Returning to the app is the phone's "reconnected": retry then. And a
// cold start IS a return — reviews persisted by a killed app must not
// wait for a state change that already happened.
AppState.addEventListener("change", (state) => {
  if (state === "active") void flush();
});
void flush();
