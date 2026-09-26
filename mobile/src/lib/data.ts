// Small data helpers shared by screens: a short-lived response cache, and
// due counts per deck.
import { api } from "./session";

const cache = new Map<string, { at: number; value: any }>();

export async function cached(path: string, ttl = 60_000) {
  const hit = cache.get(path);
  if (hit && Date.now() - hit.at < ttl) return hit.value;
  const value = await api(path);
  cache.set(path, { at: Date.now(), value });
  return value;
}

export function dropCache(prefix = "") {
  for (const key of [...cache.keys()]) if (key.startsWith(prefix)) cache.delete(key);
}

export async function dueCounts(decks: { deck_id: string }[]) {
  const results = await Promise.allSettled(
    decks.map((deck) => cached(`/api/decks/${deck.deck_id}/due`, 60_000))
  );
  const counts: Record<string, number | null> = {};
  decks.forEach((deck, index) => {
    const settled = results[index];
    counts[deck.deck_id] =
      settled.status === "fulfilled" ? settled.value.cards.length : null;
  });
  return counts;
}
