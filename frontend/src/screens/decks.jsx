// The deck library: yours, then what friends gave you. Rows navigate; every
// action lives in deck detail, because inline blur-save rename is dead.
import React, { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { cached, dueCounts } from "../data";
import { ErrorCard, Icon, Skeleton } from "../ui";

export default function Decks() {
  const navigate = useNavigate();
  const [decks, setDecks] = useState(null);
  const [counts, setCounts] = useState({});
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const { decks: all } = await cached("/api/decks", 30_000);
      setDecks(all);
      setCounts(await dueCounts(all));
    } catch (problem) {
      setError(problem.message);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  if (error) return <div className="screen"><ErrorCard message={error} onRetry={load} /></div>;
  if (!decks) return <div className="screen"><Skeleton h={56} /><Skeleton h={56} /><Skeleton h={56} /></div>;

  const bySection = {
    Yours: decks.filter((deck) => !deck.shared_with_me),
    "Shared with you": decks.filter((deck) => deck.shared_with_me),
  };

  const row = (deck) => (
    <Link key={deck.deck_id} to={`/deck/${deck.deck_id}`} className="navrow">
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontWeight: 620 }}>{deck.name}</div>
        <div className="cap">
          {deck.card_count} cards
          {deck.shared_with_me ? ` · from ${deck.owner_name}` : ""}
        </div>
      </div>
      {counts[deck.deck_id] > 0 && (
        <span className="pill pill-accent tnum">{counts[deck.deck_id]} due</span>
      )}
      <span style={{ color: "var(--muted)" }}><Icon name="chevR" size={16} /></span>
    </Link>
  );

  return (
    <div className="screen">
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div className="title">Decks</div>
        <button className="iconbtn" onClick={() => navigate("/job/new")} aria-label="Add a lecture">
          <Icon name="plus" />
        </button>
      </div>

      {decks.length === 0 && (
        <div className="card" style={{ padding: 24, display: "flex", flexDirection: "column", gap: 12 }}>
          <div className="heading">Nothing here yet</div>
          <div className="sec">Upload a lecture and this fills itself.</div>
          <button className="btn btn-primary" onClick={() => navigate("/job/new")}>
            Add your first lecture
          </button>
        </div>
      )}

      {Object.entries(bySection).map(([label, section]) =>
        section.length ? (
          <div key={label} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <div className="cap" style={{ paddingLeft: 2 }}>{label}</div>
            {[...section]
              .sort((a, b) => (counts[b.deck_id] || 0) - (counts[a.deck_id] || 0))
              .map(row)}
          </div>
        ) : null
      )}
    </div>
  );
}
