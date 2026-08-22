// Deck detail: everything the audit found homeless — rename, export, sharing,
// the card browser, per-topic mastery, run history — lives here now.
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, download } from "../session";
import { cached, dropCache } from "../data";
import { EditSheet } from "./study";
import { ErrorCard, Icon, Seg, Sheet, Skeleton, useToast } from "../ui";

export default function DeckDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const toast = useToast();

  const [deck, setDeck] = useState(null);
  const [due, setDue] = useState(null);
  const [mastery, setMastery] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [segment, setSegment] = useState("topics");
  const [cards, setCards] = useState(null);
  const [search, setSearch] = useState("");
  const [menu, setMenu] = useState(null); // null | "dots" | "rename" | "share"
  const [editing, setEditing] = useState(null);
  const [error, setError] = useState(null);
  const [studyBusy, setStudyBusy] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [deckList, jobList] = await Promise.all([
        cached("/api/decks", 30_000),
        cached("/api/jobs", 30_000),
      ]);
      const found = deckList.decks.find((d) => d.deck_id === id);
      if (!found) throw new Error("no such deck");
      setDeck(found);
      setJobs(jobList.jobs.filter((job) => job.deck_id === id));
      const [dueBody, masteryBody] = await Promise.all([
        api(`/api/decks/${id}/due`).catch(() => ({ cards: [] })),
        api(`/api/decks/${id}/mastery`).catch(() => null),
      ]);
      setDue(dueBody.cards);
      setMastery(masteryBody);
    } catch (problem) {
      setError(problem.message);
    }
  }, [id]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (segment === "cards" && cards === null) {
      api(`/api/decks/${id}/cards`).then((body) => setCards(body.cards)).catch(() => setCards([]));
    }
  }, [segment, cards, id]);

  const dueByTopic = useMemo(() => {
    const counts = {};
    for (const card of due || []) counts[card.topic_id] = (counts[card.topic_id] || 0) + 1;
    return counts;
  }, [due]);

  const latestCompleteJob = jobs.find((job) => ["complete", "reviewing"].includes(job.state));

  if (error) return <div className="mode"><div className="screen"><ErrorCard message={error} onRetry={load} /></div></div>;
  if (!deck) return <div className="mode"><div className="screen"><Skeleton h={80} /><Skeleton h={48} /><Skeleton h={200} /></div></div>;

  const startStudy = async () => {
    setStudyBusy(true);
    try {
      await api(`/api/decks/${id}/study`, { method: "POST" });
      navigate(`/study/${id}`);
    } catch (problem) {
      toast(problem.message);
      setStudyBusy(false);
    }
  };

  const exportDeck = async () => {
    if (!latestCompleteJob) {
      toast("Nothing generated to export yet");
      return;
    }
    const name = deck.name.replace(/[^\w\- ]+/g, "").trim() || "deck";
    try {
      await download(`/api/jobs/${latestCompleteJob.job_id}/deck.apkg`, `${name}.apkg`);
    } catch (problem) {
      toast(problem.message);
    }
  };

  return (
    <div className="mode" style={{ height: "auto", minHeight: "100dvh" }}>
      <div className="mode-top">
        <button className="iconbtn bare" onClick={() => navigate(-1)} aria-label="Back">
          <Icon name="chevL" />
        </button>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="title">{deck.name}</div>
          <div className="cap">
            {deck.card_count} cards
            {mastery ? ` · ${mastery.topics.length} topics` : ""}
            {deck.shared_with_me ? ` · from ${deck.owner_name}` : ""}
          </div>
        </div>
        {!deck.shared_with_me && (
          <button className="iconbtn bare" onClick={() => setMenu("dots")} aria-label="More">
            <Icon name="dots" />
          </button>
        )}
      </div>

      <div className="screen" style={{ paddingTop: 4 }}>
        <button className="btn btn-primary" onClick={startStudy} disabled={studyBusy}>
          {studyBusy ? "Opening…" : due?.length ? `Study ${due.length} due` : "Study ahead"}
        </button>

        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn btn-ghost" style={{ flex: 1, fontSize: "var(--type-secondary)" }}
            onClick={() => navigate(`/job/new?deck=${id}`)} disabled={deck.shared_with_me}>
            <Icon name="doc" size={16} /> Add lecture
          </button>
          <button className="btn btn-ghost" style={{ flex: 1, fontSize: "var(--type-secondary)" }}
            onClick={() => setMenu("share")} disabled={deck.shared_with_me}>
            <Icon name="share" size={16} /> Share
          </button>
          <button className="btn btn-ghost" style={{ flex: 1, fontSize: "var(--type-secondary)" }}
            onClick={exportDeck}>
            <Icon name="download" size={16} /> Export .apkg
          </button>
        </div>

        <Seg
          options={[["topics", "Topics"], ["cards", "Cards"], ["history", "History"]]}
          value={segment}
          onChange={setSegment}
        />

        {segment === "topics" && (
          <div className="list">
            {!mastery && <Skeleton h={52} />}
            {mastery?.topics.map((topic) => {
              const topicId =
                topic.topic_id ||
                (due || []).find((c) => c.deck_path === topic.deck_path)?.topic_id;
              const dueHere = Object.entries(dueByTopic)
                .filter(([tid]) => (due || []).some((c) => c.topic_id === tid && c.deck_path === topic.deck_path))
                .reduce((sum, [, n]) => sum + n, 0);
              const pct = Math.round(topic.mastery * 100);
              return (
                <button key={topic.deck_path} className="navrow"
                  onClick={() => topicId && latestCompleteJob
                    ? navigate(`/deck/${id}/topic/${topicId}`)
                    : undefined}>
                  <div style={{ flex: 1, minWidth: 0, textAlign: "left" }}>
                    <div style={{ fontWeight: 620 }}>{topic.deck_path.split("::").pop()}</div>
                    {/* Copy rule: decayed retrievability is "due for review",
                        never "forgotten". */}
                    {pct < 40 && topic.mastery > 0 && <div className="cap">due for review</div>}
                  </div>
                  <div className="bar" style={{ width: 56 }}><div style={{ width: `${pct}%` }} /></div>
                  <span className="cap tnum" style={{ width: 34, textAlign: "right", fontWeight: 620 }}>{pct}%</span>
                  {dueHere > 0 && <span className="pill pill-accent tnum">{dueHere}</span>}
                </button>
              );
            })}
            {mastery && !mastery.topics.length && (
              <div className="sec">No cards yet — generation may still be running.</div>
            )}
          </div>
        )}

        {segment === "cards" && (
          <>
            <input className="field" placeholder="Search cards" value={search}
              onChange={(e) => setSearch(e.target.value)} />
            <div className="list">
              {cards === null && <Skeleton h={52} />}
              {(cards || [])
                .filter((card) =>
                  (card.front + card.back).toLowerCase().includes(search.toLowerCase()))
                .slice(0, 100)
                .map((card) => (
                  <button key={card.card_uuid} className="navrow" onClick={() => setEditing(card)}>
                    <div style={{ flex: 1, minWidth: 0, textAlign: "left" }}>
                      <div style={{ fontWeight: 620, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {card.front}
                      </div>
                      <div className="cap" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {card.back}
                      </div>
                    </div>
                    <span style={{ color: "var(--muted)" }}><Icon name="edit" size={16} /></span>
                  </button>
                ))}
            </div>
          </>
        )}

        {segment === "history" && (
          <div className="list">
            {jobs.length === 0 && <div className="sec">No uploads yet.</div>}
            {jobs.map((job) => (
              <div key={job.job_id} className="rowcard"
                style={{ display: "flex", alignItems: "center", gap: 10, padding: "12px 14px" }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: "var(--type-secondary)", fontWeight: 620 }}>
                    {job.source_filename}
                  </div>
                  <div className="cap">
                    {new Date(job.created_at).toLocaleDateString()} ·{" "}
                    {job.state === "failed" ? job.error || "failed" : job.state}
                    {job.card_count ? ` · ${job.card_count} cards` : ""}
                  </div>
                </div>
                {["interrupted", "failed", "plan_ready", "generating", "planning"].includes(job.state) && (
                  <button className="btn btn-ghost btn-small" onClick={() => navigate(`/job/${job.job_id}`)}>
                    {job.state === "interrupted" ? "Resume" : job.state === "failed" ? "Retry" : "Open"}
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {menu === "dots" && (
        <Sheet onClose={() => setMenu(null)}>
          <button className="btn btn-ghost" onClick={() => setMenu("rename")}>Rename</button>
        </Sheet>
      )}
      {menu === "rename" && (
        <RenameSheet deck={deck} onClose={() => setMenu(null)}
          onDone={(name) => { setDeck({ ...deck, name }); setMenu(null); dropCache("/api/decks"); }} />
      )}
      {menu === "share" && <ShareSheet deckId={id} onClose={() => setMenu(null)} />}
      {editing && (
        <EditSheet card={editing} onClose={() => setEditing(null)}
          onSaved={(front, back) => {
            setCards((current) =>
              current.map((c) => (c.card_uuid === editing.card_uuid ? { ...c, front, back } : c)));
            setEditing(null);
            toast("Card updated");
          }} />
      )}
    </div>
  );
}

function RenameSheet({ deck, onClose, onDone }) {
  const [name, setName] = useState(deck.name);
  const [error, setError] = useState(null);

  const save = async () => {
    setError(null);
    try {
      await api(`/api/decks/${deck.deck_id}`, {
        method: "PATCH",
        body: JSON.stringify({ name }),
      });
      onDone(name);
    } catch (problem) {
      // An explicit inline error, never a silent revert.
      setError(problem.message);
    }
  };

  return (
    <Sheet onClose={onClose}>
      <div className="heading">Rename deck</div>
      <input className="field" value={name} autoFocus onChange={(e) => setName(e.target.value)} />
      {error && <span className="sec" style={{ color: "var(--danger)" }}>{error}</span>}
      <div style={{ display: "flex", gap: 8 }}>
        <button className="btn btn-ghost" style={{ flex: 1 }} onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" style={{ flex: 1 }} onClick={save} disabled={!name.trim()}>
          Save
        </button>
      </div>
    </Sheet>
  );
}

function ShareSheet({ deckId, onClose }) {
  const navigate = useNavigate();
  const toast = useToast();
  const [friends, setFriends] = useState(null);

  useEffect(() => {
    api("/api/friends").then((circle) => setFriends(circle.friends)).catch(() => setFriends([]));
  }, []);

  const give = async (person) => {
    try {
      await api(`/api/decks/${deckId}/share`, {
        method: "POST",
        body: JSON.stringify({ account_id: person.account_id }),
      });
      toast(`Shared with ${person.display_name || "them"}`);
      onClose();
    } catch (problem) {
      toast(problem.message);
    }
  };

  return (
    <Sheet onClose={onClose}>
      <div className="heading">Share this deck</div>
      {friends === null && <Skeleton h={44} />}
      {friends?.length === 0 && (
        <>
          <div className="sec">
            Sharing needs a friend first — add one with their code on the Leaderboard.
          </div>
          <button className="btn btn-primary" onClick={() => navigate("/leaderboard")}>
            Go to Leaderboard
          </button>
        </>
      )}
      {friends?.map((person) => (
        <button key={person.account_id} className="btn btn-ghost" onClick={() => give(person)}>
          {person.display_name || person.account_id.slice(0, 8)}
        </button>
      ))}
    </Sheet>
  );
}
