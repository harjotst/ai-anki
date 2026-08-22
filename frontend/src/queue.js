// The review queue: the reason a rating never waits on the network.
//
// Every answer is appended here and the UI advances immediately; batches are
// flushed to POST /api/reviews, which is idempotent on the client-chosen id —
// so a flush that died mid-flight is retried without answering twice, and a
// person on hospital wifi studies at exactly the speed they would offline.
//
// Storage sits behind a two-function adapter and ids behind uuid(), because
// these are two of the four seams the React Native app fills later.
import { api } from "./session";

export const uuid = () =>
  window.crypto?.randomUUID
    ? window.crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;

const KEY = "ai_anki_review_queue";
const storage = {
  read() {
    try {
      return JSON.parse(window.localStorage.getItem(KEY) || "[]");
    } catch {
      return [];
    }
  },
  write(rows) {
    window.localStorage.setItem(KEY, JSON.stringify(rows));
  },
};

const listeners = new Set();
const notify = () => listeners.forEach((fn) => fn(pendingCount()));

export function pendingCount() {
  return storage.read().length;
}

export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function enqueue(review) {
  storage.write([...storage.read(), review]);
  notify();
  void flush();
}

/** Undo support: remove a review that has not been flushed yet. Returns
 *  whether it was still here — if not, it already reached the server and the
 *  undo becomes a superseding review instead of a retraction. */
export function removeQueued(clientUuid) {
  const rows = storage.read();
  const kept = rows.filter((row) => row.client_uuid !== clientUuid);
  if (kept.length === rows.length) return false;
  storage.write(kept);
  notify();
  return true;
}

let flushing = false;

export async function flush() {
  if (flushing) return;
  const batch = storage.read();
  if (!batch.length) return;
  flushing = true;
  try {
    await api("/api/reviews", {
      method: "POST",
      body: JSON.stringify({ reviews: batch }),
    });
    // Only drop what was sent; anything enqueued during the flight stays.
    storage.write(storage.read().slice(batch.length));
  } catch {
    // Still queued; the next trigger retries. Silence is correct here — the
    // sync pill in the study screen is the honest surface for this state.
  } finally {
    flushing = false;
    notify();
  }
}

// Retry on reconnect and on returning to the app — the two moments a flaky
// connection is most likely to have come back.
window.addEventListener("online", () => void flush());
window.addEventListener("focus", () => void flush());
