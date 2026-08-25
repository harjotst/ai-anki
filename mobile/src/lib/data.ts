// Small data helpers shared by screens — ported from the web's data.js with
// identical semantics, because the streak a person sees must not depend on
// which renderer computed it.
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

/** The device's own calendar date — days from the server are bucketed in
 *  this timezone too, so the two always name the same square. */
export function localDay(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

export function streakFrom(days: { day: string }[], now = new Date()) {
  const studied = new Set(days.map((d) => d.day));
  const iso = localDay;
  // By calendar day, never by 24 hours: a local day is 23 or 25 hours twice
  // a year, and fixed-milliseconds stepping skips or repeats a day exactly
  // when someone studies near midnight across a DST change.
  const dayBefore = (date: Date) => {
    const previous = new Date(date);
    previous.setDate(previous.getDate() - 1);
    return previous;
  };

  const today = iso(now);
  const studiedToday = studied.has(today);
  let cursor = studiedToday ? now : dayBefore(now);
  if (!studied.has(iso(cursor))) {
    return { streak: 0, banked: 0, covered: [] as string[], studiedToday };
  }

  let streak = 0;
  let banked = 0;
  let earnedRun = 0;
  const covered: string[] = [];
  while (true) {
    const key = iso(cursor);
    if (studied.has(key)) {
      streak += 1;
      earnedRun += 1;
      if (earnedRun % 7 === 0) banked = Math.min(2, banked + 1);
    } else if (banked > 0 && studied.has(iso(dayBefore(cursor)))) {
      banked -= 1;
      covered.push(key);
      streak += 1;
    } else {
      break;
    }
    cursor = dayBefore(cursor);
  }
  return { streak, banked, covered, studiedToday };
}

export function heatCells(days: { day: string; reviews: number }[], now = new Date(), weeks = 12) {
  const byDay = Object.fromEntries(days.map((d) => [d.day, d.reviews]));
  const total = weeks * 7;
  const cells: { day: string; count: number; level: number }[] = [];
  for (let back = total - 1; back >= 0; back--) {
    const date = new Date(now);
    date.setDate(date.getDate() - back);
    const key = localDay(date);
    const count = byDay[key] || 0;
    const level = count === 0 ? 0 : count < 5 ? 1 : count < 15 ? 2 : count < 40 ? 3 : 4;
    cells.push({ day: key, count, level });
  }
  return cells;
}
