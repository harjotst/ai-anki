// Small data helpers shared by screens: short-lived caches for the reads the
// shell repeats, and the streak arithmetic derived from activity history.
import { api } from "./session";

const cache = new Map();

/** A GET with a short memory, so Today and the shell can re-render without
 *  re-fetching. TTL in ms; a failed fetch is never cached. */
export async function cached(path, ttl = 60_000) {
  const hit = cache.get(path);
  if (hit && Date.now() - hit.at < ttl) return hit.value;
  const value = await api(path);
  cache.set(path, { at: Date.now(), value });
  return value;
}

export function dropCache(prefix = "") {
  for (const key of [...cache.keys()]) if (key.startsWith(prefix)) cache.delete(key);
}

/** Due counts per deck. No bulk endpoint exists yet (first item on the
 *  backend wishlist), so this is parallel per-deck fetches — acknowledged
 *  fine to ~20 decks. allSettled: one deck failing must not blank the rest. */
export async function dueCounts(decks) {
  const results = await Promise.allSettled(
    decks.map((deck) => cached(`/api/decks/${deck.deck_id}/due`, 60_000))
  );
  const counts = {};
  decks.forEach((deck, index) => {
    const settled = results[index];
    counts[deck.deck_id] =
      settled.status === "fulfilled" ? settled.value.cards.length : null;
  });
  return counts;
}

/** The streak, with banked rest days — G2, computed display-side.
 *
 *  Every 7 consecutive studied days banks one silent cover, at most 2 held;
 *  a single missed day is covered by a banked one and the streak holds. The
 *  server's strict streak (leaderboard) is untouched: this is the display
 *  grace, and the copy stays quiet about it — "Day 12 held — a rest day
 *  covered Tuesday", never a guilt trip.
 */
export function streakFrom(days, now = new Date()) {
  const studied = new Set(days.map((d) => d.day));
  const iso = (date) => date.toISOString().slice(0, 10);
  const dayBefore = (date) => new Date(date.getTime() - 86_400_000);

  const today = iso(now);
  const studiedToday = studied.has(today);
  // Not having studied by 9 am is not a broken streak; start from yesterday.
  let cursor = studiedToday ? now : dayBefore(now);
  if (!studied.has(iso(cursor))) {
    // Neither today nor yesterday: whatever run exists has already ended.
    return { streak: 0, banked: 0, covered: [], studiedToday };
  }

  let streak = 0;
  let banked = 0;
  let earnedRun = 0;
  const covered = [];
  while (true) {
    const key = iso(cursor);
    if (studied.has(key)) {
      streak += 1;
      earnedRun += 1;
      if (earnedRun % 7 === 0) banked = Math.min(2, banked + 1);
    } else if (banked > 0 && studied.has(iso(dayBefore(cursor)))) {
      // A rest day covers a gap INSIDE the run — never the empty days before
      // the streak began, which would quietly inflate it.
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

/** 12 weeks of heatmap cells, oldest first, one entry per day. */
export function heatCells(days, now = new Date(), weeks = 12) {
  const byDay = Object.fromEntries(days.map((d) => [d.day, d.reviews]));
  const total = weeks * 7;
  const cells = [];
  for (let back = total - 1; back >= 0; back--) {
    const date = new Date(now.getTime() - back * 86_400_000);
    const key = date.toISOString().slice(0, 10);
    const count = byDay[key] || 0;
    // Steps scaled to a person starting out, not only to a 200-card grinder —
    // a real study day must never be near-invisible on the map.
    const level = count === 0 ? 0 : count < 5 ? 1 : count < 15 ? 2 : count < 40 ? 3 : 4;
    cells.push({ day: key, count, level });
  }
  return cells;
}
