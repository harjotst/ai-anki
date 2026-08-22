// Topic-by-topic comparison on a shared deck — one friend at a time, with the
// grinder's actual question answered by the gap sort: where are they ahead?
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../session";
import { cached } from "../data";
import { ErrorCard, Icon, Seg, Skeleton } from "../ui";

export default function Compare() {
  const { deckId } = useParams();
  const navigate = useNavigate();
  const [compared, setCompared] = useState(null);
  const [deckName, setDeckName] = useState("");
  const [friend, setFriend] = useState(null);
  const [sort, setSort] = useState("gap");
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [body, decks] = await Promise.all([
        api(`/api/decks/${deckId}/compare`),
        cached("/api/decks", 60_000),
      ]);
      setCompared(body);
      setDeckName(decks.decks.find((d) => d.deck_id === deckId)?.name || "");
      if (body.friends.length) setFriend(body.friends[0].account_id);
    } catch (problem) {
      setError(problem.message);
    }
  }, [deckId]);

  useEffect(() => { load(); }, [load]);

  const other = compared?.friends.find((f) => f.account_id === friend);

  const rows = useMemo(() => {
    if (!compared || !other) return [];
    const theirs = Object.fromEntries(other.topics.map((t) => [t.deck_path, t.mastery]));
    const built = compared.you.topics.map((topic) => ({
      path: topic.deck_path,
      you: Math.round(topic.mastery * 100),
      them: Math.round((theirs[topic.deck_path] || 0) * 100),
    }));
    if (sort === "gap") built.sort((a, b) => (a.you - a.them) - (b.you - b.them));
    return built;
  }, [compared, other, sort]);

  const weakest = useMemo(() => {
    if (!compared) return null;
    const sorted = [...compared.you.topics].sort((a, b) => a.mastery - b.mastery);
    return sorted[0] || null;
  }, [compared]);

  if (error) return <div className="mode"><div className="screen"><ErrorCard message={error} onRetry={load} /></div></div>;
  if (!compared) return <div className="mode"><div className="screen"><Skeleton h={60} /><Skeleton h={200} /></div></div>;

  return (
    <div className="mode" style={{ height: "auto", minHeight: "100dvh" }}>
      <div className="mode-top">
        <button className="iconbtn bare" onClick={() => navigate(-1)} aria-label="Back">
          <Icon name="chevL" />
        </button>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="heading">{deckName}</div>
          <div className="cap">topic by topic, against one friend</div>
        </div>
      </div>

      <div className="screen" style={{ paddingTop: 4 }}>
        {compared.friends.length === 0 ? (
          <div className="card" style={{ padding: 20, display: "flex", flexDirection: "column", gap: 12 }}>
            <div className="sec">{compared.why_empty}</div>
            <button className="btn btn-primary" onClick={() => navigate(`/deck/${deckId}`)}>
              Share this deck
            </button>
          </div>
        ) : (
          <>
            <div style={{ display: "flex", gap: 8 }}>
              {compared.friends.length > 1 && (
                <Seg
                  style={{ flex: 1 }}
                  options={compared.friends.map((f) => [
                    f.account_id,
                    f.display_name || f.account_id.slice(0, 6),
                  ])}
                  value={friend}
                  onChange={setFriend}
                />
              )}
              <Seg
                style={{ flex: 1.3 }}
                options={[["order", "By order"], ["gap", "Biggest gap"]]}
                value={sort}
                onChange={setSort}
              />
            </div>

            <div className="list">
              {rows.map((row) => (
                <div key={row.path} className="rowcard"
                  style={{ padding: "12px 14px", display: "flex", flexDirection: "column", gap: 8 }}>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
                    <span style={{ fontSize: "var(--type-secondary)", fontWeight: 620 }}>
                      {row.path.split("::").pop()}
                    </span>
                    {/* Muted, and only when ahead — the bars already say the rest. */}
                    {row.you > row.them && (
                      <span className="pill pill-neutral tnum">+{row.you - row.them}</span>
                    )}
                  </div>
                  <BarRow label="You" value={row.you} accent />
                  <BarRow label={other?.display_name?.split(" ")[0] || "Them"} value={row.them} />
                </div>
              ))}
            </div>

            {weakest && (
              <button className="btn btn-primary" onClick={() => navigate(`/study/${deckId}`)}>
                Study your weakest topic
              </button>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function BarRow({ label, value, accent }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <span className="cap" style={{ width: 34 }}>{label}</span>
      <div className="bar" style={{ flex: 1 }}>
        <div style={{ width: `${value}%`, background: accent ? "var(--accent)" : "var(--border-strong)" }} />
      </div>
      <span className="cap tnum" style={{ width: 26, textAlign: "right", fontWeight: 620, color: accent ? "var(--text)" : "var(--text-2)" }}>
        {value}
      </span>
    </div>
  );
}
