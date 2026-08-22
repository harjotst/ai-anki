// The leaderboard, named what it is and living in primary navigation.
import React, { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../session";
import { cached, dropCache } from "../data";
import { ErrorCard, Icon, Skeleton, useToast } from "../ui";

const DEFINITIONS = {
  reviews: "How many answers were given in the window — work done, not knowledge held.",
  streak: "Consecutive days with at least one review, ending today.",
  known: "Cards you would recall right now. Unlike a review count, it goes down when you stop.",
};

export default function Leaderboard() {
  const navigate = useNavigate();
  const toast = useToast();
  const [board, setBoard] = useState(null);
  const [circle, setCircle] = useState(null);
  const [me, setMe] = useState(null);
  const [decks, setDecks] = useState([]);
  const [code, setCode] = useState("");
  const [tip, setTip] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [boardBody, circleBody, meBody, deckBody] = await Promise.all([
        api("/api/leaderboard"),
        api("/api/friends"),
        cached("/api/me", 300_000),
        cached("/api/decks", 60_000),
      ]);
      setBoard(boardBody);
      setCircle(circleBody);
      setMe(meBody);
      setDecks(deckBody.decks);
    } catch (problem) {
      setError(problem.message);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  if (error) return <div className="screen"><ErrorCard message={error} onRetry={load} /></div>;
  if (!board || !circle || !me)
    return <div className="screen"><Skeleton h={40} /><Skeleton h={180} /><Skeleton h={80} /></div>;

  const add = async (event) => {
    event.preventDefault();
    try {
      await api("/api/friends", {
        method: "POST",
        body: JSON.stringify({ code: code.trim().toUpperCase() }),
      });
      setCode("");
      dropCache("/api/friends");
      toast("Request sent");
      load();
    } catch (problem) {
      toast(problem.message);
    }
  };

  const act = async (path, options) => {
    try {
      await api(path, options);
      dropCache("/api/friends");
      load();
    } catch (problem) {
      toast(problem.message);
    }
  };

  const header = (key, label, width) => (
    <button className="cap" style={{ width, textAlign: "right", display: "inline-flex", justifyContent: "flex-end", alignItems: "center", gap: 3 }}
      onClick={() => setTip(tip === key ? null : key)}>
      {label} <Icon name="info" size={11} />
    </button>
  );

  return (
    <div className="screen">
      <div className="title">Leaderboard</div>

      {circle.incoming.map((person) => (
        <div key={person.account_id}
          style={{ display: "flex", alignItems: "center", gap: 10, background: "var(--accent-soft)", borderRadius: "var(--radius-md)", padding: "8px 8px 8px 14px" }}>
          <span style={{ flex: 1, fontSize: "var(--type-secondary)", fontWeight: 620 }}>
            {person.display_name || "Somebody"} wants to study with you
          </span>
          <button className="btn btn-primary btn-small"
            onClick={() => act(`/api/friends/${person.account_id}/accept`, { method: "POST" })}>
            Accept
          </button>
          <button className="btn btn-ghost btn-small"
            onClick={() => act(`/api/friends/${person.account_id}`, { method: "DELETE" })}>
            Decline
          </button>
        </div>
      ))}

      <div className="card" style={{ padding: 6 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 14px 4px" }}>
          <span style={{ width: 18 }} />
          <span style={{ flex: 1 }} />
          {header("reviews", "Reviews (this wk)", 96)}
          {header("streak", "Streak", 52)}
          {header("known", "Known", 52)}
        </div>
        {tip && (
          <div className="cap" style={{ padding: "0 14px 8px", color: "var(--text-2)" }}>
            {DEFINITIONS[tip]}
          </div>
        )}
        {board.rows.map((row, index) => (
          <div key={row.account_id}
            style={{
              display: "flex", alignItems: "center", gap: 10, padding: "12px 14px", minHeight: 52,
              background: row.is_you ? "var(--accent-soft)" : "transparent",
              borderRadius: "var(--radius-md)",
            }}>
            <span className="tnum" style={{ width: 18, color: "var(--muted)", fontSize: "var(--type-secondary)" }}>
              {index + 1}
            </span>
            <span style={{ flex: 1, fontWeight: row.is_you ? 620 : 500 }}>
              {row.is_you ? "You" : row.display_name || row.account_id.slice(0, 8)}
            </span>
            <span className="tnum" style={{ width: 96, textAlign: "right" }}>{row.reviews}</span>
            <span className="tnum" style={{ width: 52, textAlign: "right" }}>
              {row.streak_days ? `${row.streak_days}d` : "—"}
            </span>
            <span className="tnum" style={{ width: 52, textAlign: "right" }}>{row.cards_known}</span>
          </div>
        ))}
      </div>
      <p className="cap">
        Reviews is work done this week. Known is what you would recall right now —
        it goes down if you stop, which a review count never does.
      </p>

      <form style={{ display: "flex", gap: 8 }} onSubmit={add}>
        <input className="field" style={{ flex: 1 }} placeholder="a friend's code"
          value={code} maxLength={12} onChange={(e) => setCode(e.target.value)} />
        <button type="submit" className="btn btn-primary" disabled={!code.trim()}>Add</button>
      </form>

      <div className="card" style={{ padding: 16, display: "flex", alignItems: "center", gap: 12 }}>
        <div style={{ flex: 1 }}>
          <div className="cap">Your friend code</div>
          <div className="mono" style={{ fontSize: 17, letterSpacing: ".14em", fontWeight: 620, marginTop: 2 }}>
            {me.friend_code}
          </div>
        </div>
        <button className="iconbtn" aria-label="Copy code"
          onClick={() => { navigator.clipboard?.writeText(me.friend_code); toast("Copied"); }}>
          <Icon name="copy" size={18} />
        </button>
        {navigator.share && (
          <button className="iconbtn" aria-label="Share code"
            onClick={() => navigator.share({ text: `Study with me on ai-anki — my code is ${me.friend_code}` }).catch(() => {})}>
            <Icon name="share" size={18} />
          </button>
        )}
      </div>

      {circle.friends.length > 0 && decks.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <div className="cap" style={{ paddingLeft: 2 }}>Compare on a shared deck</div>
          {decks.map((deck) => (
            <button key={deck.deck_id} className="navrow" onClick={() => navigate(`/compare/${deck.deck_id}`)}>
              <span style={{ flex: 1, textAlign: "left", fontWeight: 620 }}>{deck.name}</span>
              <span style={{ color: "var(--muted)" }}><Icon name="chevR" size={16} /></span>
            </button>
          ))}
        </div>
      )}

      {circle.outgoing.length > 0 && (
        <p className="cap">
          Waiting on {circle.outgoing.length} request{circle.outgoing.length > 1 ? "s" : ""} to be accepted.
        </p>
      )}
    </div>
  );
}
