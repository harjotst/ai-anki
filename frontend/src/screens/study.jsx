// The study session. The rule that shapes everything here: a rating never
// waits on the network. Answers go to the local queue (queue.js) and the UI
// advances instantly; the queue flushes in idempotent batches behind the
// person's back, and the only trace of the network is the quiet sync pill.
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../session";
import { enqueue, pendingCount, removeQueued, subscribe, uuid } from "../queue";
import { cached, dropCache, dueCounts } from "../data";
import { CardText, ErrorCard, Icon, Sheet, Skeleton, useToast } from "../ui";

const RATING_META = [
  ["again", "Again", "rate-again"],
  ["hard", "Hard", ""],
  ["good", "Good", "rate-good"],
  ["easy", "Easy", ""],
];

export default function Study() {
  const { deckId } = useParams();
  const navigate = useNavigate();
  const toast = useToast();

  const [queue, setQueue] = useState(null);
  const [revealed, setRevealed] = useState(false);
  const [log, setLog] = useState([]);
  const [pending, setPending] = useState(pendingCount());
  const [menu, setMenu] = useState(null); // null | "overflow" | "edit" | "info"
  const [error, setError] = useState(null);
  const [baselineKnown, setBaselineKnown] = useState(null);
  const shownAt = useRef(Date.now());
  const deckName = useRef("");

  const load = useCallback(async () => {
    setError(null);
    setQueue(null);
    setLog([]);
    try {
      let cards = [];
      if (deckId === "all") {
        // Chain every deck with work, largest first: one tap, no deciding.
        const { decks } = await api("/api/decks");
        const buckets = [];
        for (const deck of decks) {
          await api(`/api/decks/${deck.deck_id}/study`, { method: "POST" }).catch(() => {});
          const due = await api(`/api/decks/${deck.deck_id}/due`).catch(() => ({ cards: [] }));
          if (due.cards.length) buckets.push({ deck, cards: due.cards });
        }
        buckets.sort((a, b) => b.cards.length - a.cards.length);
        cards = buckets.flatMap((bucket) => bucket.cards);
        deckName.current = buckets.length === 1 ? buckets[0].deck.name : "All decks";
      } else {
        await api(`/api/decks/${deckId}/study`, { method: "POST" });
        const [due, decks] = await Promise.all([
          api(`/api/decks/${deckId}/due`),
          cached("/api/decks", 60_000),
        ]);
        cards = due.cards;
        deckName.current =
          decks.decks.find((d) => d.deck_id === deckId)?.name || "Study";
      }
      setQueue(cards);
      shownAt.current = Date.now();
      cached("/api/leaderboard", 0)
        .then((board) => {
          const me = board.rows.find((row) => row.is_you);
          setBaselineKnown(me ? me.cards_known : null);
        })
        .catch(() => {});
    } catch (problem) {
      setError(problem.message);
    }
  }, [deckId]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => subscribe(setPending), []);

  const card = queue?.[0];

  const rate = useCallback(
    (rating) => {
      if (!card) return;
      const review = {
        client_uuid: uuid(),
        card_uuid: card.card_uuid,
        rating,
        reviewed_at: new Date().toISOString(),
        duration_ms: Date.now() - shownAt.current,
      };
      enqueue(review);
      setLog((entries) => [...entries, { card, rating, client_uuid: review.client_uuid, ms: review.duration_ms }]);
      setQueue((current) => {
        const rest = current.slice(1);
        // Local re-queue is session convenience, not scheduling authority:
        // the server's next-due wins the moment the queue is refetched.
        if (rating === "again") rest.splice(Math.min(10, rest.length), 0, card);
        if (rating === "hard") rest.push(card);
        return rest;
      });
      setRevealed(false);
      shownAt.current = Date.now();
    },
    [card]
  );

  const undo = useCallback(() => {
    setLog((entries) => {
      if (!entries.length) return entries;
      const last = entries[entries.length - 1];
      // Unflushed: the rating simply never happened. Flushed: it stands in
      // history, and the next rating supersedes it in event order.
      removeQueued(last.client_uuid);
      setQueue((current) => {
        const withoutRequeue = [...current];
        const requeued = withoutRequeue.findIndex(
          (c) => c.card_uuid === last.card.card_uuid
        );
        if (requeued >= 0 && ["again", "hard"].includes(last.rating)) {
          withoutRequeue.splice(requeued, 1);
        }
        return [last.card, ...withoutRequeue];
      });
      setRevealed(false);
      shownAt.current = Date.now();
      return entries.slice(0, -1);
    });
  }, []);

  useEffect(() => {
    const onKey = (event) => {
      if (menu || /INPUT|TEXTAREA/.test(event.target.tagName)) return;
      if (event.key === " " || event.key === "Enter") {
        event.preventDefault();
        setRevealed(true);
      } else if (revealed && ["1", "2", "3", "4"].includes(event.key)) {
        rate(RATING_META[Number(event.key) - 1][0]);
      } else if (event.key.toLowerCase() === "z") {
        undo();
      } else if (event.key.toLowerCase() === "e" && card) {
        setMenu("edit");
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [menu, revealed, rate, undo, card]);

  if (error) return <div className="mode"><div className="screen"><ErrorCard message={error} onRetry={load} /></div></div>;
  if (!queue) return <div className="mode"><div className="screen"><Skeleton h={200} /></div></div>;
  if (!card) return <Complete log={log} deckId={deckId} baselineKnown={baselineKnown} />;

  const done = log.length;
  const total = done + queue.length;
  const offline = !navigator.onLine;

  return (
    <div className="mode">
      <div className="mode-top">
        <button className="iconbtn bare" onClick={() => navigate("/today")} aria-label="Stop for now">
          <Icon name="x" />
        </button>
        <span className="cap" style={{ flex: 1, textAlign: "center" }}>{deckName.current}</span>
        <button className="iconbtn bare" onClick={() => setMenu("overflow")} aria-label="More">
          <Icon name="dots" />
        </button>
      </div>
      <div style={{ padding: "0 16px" }}>
        <div className="hairline"><div style={{ width: `${(done / Math.max(1, total)) * 100}%` }} /></div>
        <div style={{ display: "flex", justifyContent: "space-between", marginTop: 8 }}>
          <span className="cap tnum">{done} / {total}</span>
          {(pending > 0 || offline) && (
            <span className="pill pill-warn tnum">
              {offline ? `offline · ${pending} queued` : `syncing ${pending}`}
            </span>
          )}
        </div>
      </div>

      <div className="mode-body" style={{ display: "flex", flexDirection: "column", justifyContent: "center", padding: 24 }}>
        <div style={{ fontWeight: 620 }}>
          <CardText text={card.rendered_front || card.front} />
        </div>
        {revealed && (
          <>
            <div style={{ height: 1, background: "var(--border)", margin: "20px 0" }} />
            <div style={{ color: "var(--text-2)" }}>
              <CardText text={card.back || card.front} />
            </div>
            <div className="cap" style={{ marginTop: 16 }}>{card.deck_path}</div>
          </>
        )}
      </div>

      <div className="mode-bottom" style={{ borderTop: "none", background: "transparent" }}>
        {revealed ? (
          <>
            <div className="ratings">
              {RATING_META.map(([key, label, cls]) => (
                <button key={key} className={`rate ${cls}`} onClick={() => rate(key)}>
                  <span>{label}</span>
                  {card.previews?.[key] && <span className="cap tnum">{card.previews[key]}</span>}
                </button>
              ))}
            </div>
            <div className="cap kbd-hint" style={{ textAlign: "center", marginTop: 8 }}>
              1 – 4 to rate · Z undo · E edit
            </div>
          </>
        ) : (
          <>
            <button className="btn btn-primary" style={{ width: "100%", minHeight: "var(--target-rating)" }}
              onClick={() => setRevealed(true)}>
              Show answer
            </button>
            <div className="cap kbd-hint" style={{ textAlign: "center", marginTop: 8 }}>
              Space to reveal
            </div>
          </>
        )}
      </div>

      {menu === "overflow" && (
        <Sheet onClose={() => setMenu(null)}>
          <button className="btn btn-ghost" onClick={() => setMenu("edit")}>Edit card</button>
          <button className="btn btn-ghost" onClick={() => setMenu("info")}>Card info</button>
          <button className="btn btn-ghost" onClick={() => { undo(); setMenu(null); }} disabled={!log.length}>
            Undo last
          </button>
        </Sheet>
      )}
      {menu === "edit" && (
        <EditSheet
          card={card}
          onClose={() => setMenu(null)}
          onSaved={(front, back) => {
            setQueue((current) => [
              { ...current[0], front, back, rendered_front: current[0].note_type === "cloze" ? current[0].rendered_front : front },
              ...current.slice(1),
            ]);
            setMenu(null);
            toast("Card updated");
          }}
        />
      )}
      {menu === "info" && (
        <Sheet onClose={() => setMenu(null)}>
          <div className="heading">Card info</div>
          {/* Only what the payload actually carries — absent fields are
              omitted, never faked. */}
          <InfoRow label="State" value={card.state} />
          <InfoRow label="Reviews" value={card.reps} />
          {card.stability != null && <InfoRow label="Stability" value={`${card.stability.toFixed(1)} d`} />}
          <InfoRow label="Due" value={new Date(card.due).toLocaleString()} />
          <InfoRow label="Deck path" value={card.deck_path} />
        </Sheet>
      )}
    </div>
  );
}

function InfoRow({ label, value }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 12, minHeight: 28 }}>
      <span className="sec">{label}</span>
      <span className="tnum" style={{ fontWeight: 620 }}>{String(value)}</span>
    </div>
  );
}

export function EditSheet({ card, onClose, onSaved }) {
  const [front, setFront] = useState(card.front);
  const [back, setBack] = useState(card.back);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await api(`/api/cards/${card.card_uuid}`, {
        method: "PATCH",
        body: JSON.stringify({ front, back }),
      });
      onSaved(front, back);
    } catch (problem) {
      setError(problem.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Sheet onClose={onClose}>
      <div className="heading">Edit card</div>
      <textarea className="field" value={front} onChange={(e) => setFront(e.target.value)} />
      <textarea className="field" value={back} onChange={(e) => setBack(e.target.value)} />
      {error && <span className="sec" style={{ color: "var(--danger)" }}>{error}</span>}
      <div style={{ display: "flex", gap: 8 }}>
        <button className="btn btn-ghost" style={{ flex: 1 }} onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" style={{ flex: 1 }} onClick={save} disabled={busy}>
          Save
        </button>
      </div>
    </Sheet>
  );
}

function Complete({ log, deckId, baselineKnown }) {
  const navigate = useNavigate();
  const toast = useToast();
  const [board, setBoard] = useState(null);
  const [nextDeck, setNextDeck] = useState(null);
  const [missOpen, setMissOpen] = useState(false);
  const [editing, setEditing] = useState(null);

  useEffect(() => {
    dropCache("/api");
    api("/api/leaderboard").then(setBoard).catch(() => {});
    api("/api/decks")
      .then(async ({ decks }) => {
        const counts = await dueCounts(decks);
        const candidates = decks
          .filter((deck) => deck.deck_id !== deckId && counts[deck.deck_id] > 0)
          .sort((a, b) => counts[b.deck_id] - counts[a.deck_id]);
        if (candidates.length) {
          setNextDeck({ ...candidates[0], due: counts[candidates[0].deck_id] });
        }
      })
      .catch(() => {});
  }, [deckId]);

  const reviewed = log.length;
  const misses = [...new Map(
    log.filter((entry) => entry.rating === "again").map((entry) => [entry.card.card_uuid, entry.card])
  ).values()];
  const correct = reviewed ? Math.round(((reviewed - log.filter((e) => e.rating === "again").length) / reviewed) * 100) : 0;
  const totalMs = log.reduce((sum, entry) => sum + (entry.ms || 0), 0);
  const minutes = Math.floor(totalMs / 60000);
  const seconds = Math.round((totalMs % 60000) / 1000);
  const me = board?.rows.find((row) => row.is_you);
  const ahead = board?.rows.find((row) => !row.is_you && row.reviews > (me?.reviews ?? 0));
  const knownDelta = me && baselineKnown != null ? me.cards_known - baselineKnown : null;

  return (
    <div className="mode">
      <div className="mode-body">
        <div className="screen" style={{ gap: 16, paddingTop: 44 }}>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 12 }}>
            <div style={{
              width: 56, height: 56, borderRadius: "var(--radius-pill)",
              border: "3px solid var(--accent)", color: "var(--accent)",
              display: "flex", alignItems: "center", justifyContent: "center",
            }}>
              <Icon name="check" size={26} />
            </div>
            <div className="title">Session complete</div>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0,1fr))", gap: 8 }}>
            <Stat value={reviewed} label="reviewed" />
            <Stat value={`${correct}%`} label="correct" />
            <Stat value={`${minutes}:${String(seconds).padStart(2, "0")}`} label="time" />
            <Stat value={me?.streak_days ? `Day ${me.streak_days} kept` : "—"} label="streak" small />
          </div>

          {me && (
            <div className="sec tnum" style={{ textAlign: "center" }}>
              Known {me.cards_known}{knownDelta > 0 ? ` (+${knownDelta})` : ""}
              {ahead ? ` · ${ahead.display_name || "A friend"} is ${ahead.reviews - me.reviews} reviews ahead this week` : ""}
            </div>
          )}

          {misses.length > 0 && (
            <div className="card" style={{ padding: 16, display: "flex", flexDirection: "column", gap: 10 }}>
              <button style={{ display: "flex", alignItems: "center", justifyContent: "space-between", minHeight: 28 }}
                onClick={() => setMissOpen(!missOpen)}>
                <span className="heading">{misses.length} card{misses.length > 1 ? "s" : ""} missed</span>
                <span style={{ color: "var(--muted)", transform: missOpen ? "rotate(180deg)" : "none" }}>
                  <Icon name="chevD" size={16} />
                </span>
              </button>
              {missOpen && misses.map((card) => (
                <div key={card.card_uuid} style={{ display: "flex", flexDirection: "column", gap: 6, borderTop: "1px solid var(--border)", paddingTop: 10 }}>
                  <span style={{ fontWeight: 620 }}>{card.rendered_front || card.front}</span>
                  <span className="sec">{card.back}</span>
                  <div>
                    <button className="btn btn-ghost btn-small" onClick={() => setEditing(card)}>
                      <Icon name="edit" size={14} /> Edit
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}

          <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: "auto" }}>
            {nextDeck ? (
              <button className="btn btn-primary" onClick={() => navigate(`/study/${nextDeck.deck_id}`)}>
                Next: {nextDeck.name} — {nextDeck.due} due
              </button>
            ) : (
              <button className="btn btn-primary" onClick={() => navigate("/today")}>Done</button>
            )}
            <button className="btn btn-ghost" onClick={() => navigate("/today")}>Back to Today</button>
          </div>
        </div>
      </div>
      {editing && (
        <EditSheet card={editing} onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); toast("Card updated"); }} />
      )}
    </div>
  );
}

function Stat({ value, label, small }) {
  return (
    <div className="sunken" style={{ padding: 14, display: "flex", flexDirection: "column", gap: 2 }}>
      <span className="tnum" style={{ fontSize: small ? 16 : 22, lineHeight: "26px", fontWeight: 650 }}>
        {value}
      </span>
      <span className="cap">{label}</span>
    </div>
  );
}
