// Post-generation card review — and the moment the pipeline finally lands in
// the product's own loop: the terminal action is "Study these now", not a
// download.
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, download } from "../session";
import { dropCache } from "../data";
import { EditSheet } from "./study";
import { ErrorCard, Icon, Sheet, Skeleton, useToast } from "../ui";

export default function CardsReview() {
  const { id } = useParams();
  const navigate = useNavigate();
  const toast = useToast();

  const [cards, setCards] = useState(null);
  const [job, setJob] = useState(null);
  const [picked, setPicked] = useState(() => new Set());
  const [editing, setEditing] = useState(null);
  const [busy, setBusy] = useState(null);
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState(null);
  // Soft-deletes: uuid -> timer. The DELETE fires after the undo window.
  const doomed = useRef(new Map());

  const load = useCallback(async () => {
    setError(null);
    try {
      const [body, jobBody] = await Promise.all([
        api(`/api/jobs/${id}/cards`),
        api(`/api/jobs/${id}`),
      ]);
      setCards(body.cards);
      setJob(jobBody);
    } catch (problem) {
      setError(problem.message);
    }
  }, [id]);

  useEffect(() => { load(); }, [load]);

  if (error) return <div className="mode"><div className="screen"><ErrorCard message={error} onRetry={load} /></div></div>;
  if (!cards) return <div className="mode"><div className="screen"><Skeleton h={60} /><Skeleton h={200} /></div></div>;

  const byTopic = cards.reduce((groups, card) => {
    (groups[card.deck_path] ||= []).push(card);
    return groups;
  }, {});
  const keptCount = cards.filter((card) => card.reviewed).length;

  const act = async (label, run) => {
    setBusy(label);
    try {
      await run();
    } catch (problem) {
      toast(problem.message);
    } finally {
      setBusy(null);
    }
  };

  const keep = (uuids) =>
    act("keep", async () => {
      await api(`/api/jobs/${id}/cards/accept`, {
        method: "POST",
        body: JSON.stringify({ card_uuids: uuids }),
      });
      setCards((current) =>
        current.map((card) => (uuids.includes(card.card_uuid) ? { ...card, reviewed: true } : card)));
      setPicked(new Set());
    });

  const reject = (uuids) => {
    // Optimistic removal with a 5-second undo; the server hears only if the
    // window passes. Deletion is confirmed by the snackbar, never celebrated.
    setCards((current) => current.filter((card) => !uuids.includes(card.card_uuid)));
    setPicked(new Set());
    const timer = window.setTimeout(() => {
      uuids.forEach((uuid) => doomed.current.delete(uuid));
      api(`/api/jobs/${id}/cards/reject`, {
        method: "POST",
        body: JSON.stringify({ card_uuids: uuids }),
      }).catch(() => load());
    }, 5000);
    uuids.forEach((uuid) => doomed.current.set(uuid, timer));
    toast(`${uuids.length} card${uuids.length > 1 ? "s" : ""} rejected`, {
      action: "Undo",
      ttl: 5000,
      onAction: () => {
        window.clearTimeout(timer);
        uuids.forEach((uuid) => doomed.current.delete(uuid));
        load();
      },
    });
  };

  const reroll = (card) =>
    act(card.card_uuid, async () => {
      await api(`/api/cards/${card.card_uuid}/reroll`, { method: "POST" });
      const body = await api(`/api/jobs/${id}/cards`);
      // The selection survives a single-card action — no losing forty ticks
      // to one re-roll.
      setCards(body.cards);
    });

  const studyNow = () =>
    act("study", async () => {
      await api(`/api/decks/${job.deck_id}/study`, { method: "POST" });
      dropCache("/api");
      navigate(`/study/${job.deck_id}`);
    });

  const toggle = (uuid) =>
    setPicked((current) => {
      const next = new Set(current);
      next.has(uuid) ? next.delete(uuid) : next.add(uuid);
      return next;
    });

  return (
    <div className="mode" style={{ height: "auto", minHeight: "100dvh", paddingBottom: picked.size ? 88 : 0 }}>
      <div className="mode-top">
        <button className="iconbtn bare" onClick={() => navigate(-1)} aria-label="Back">
          <Icon name="chevL" />
        </button>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="heading">Look them over</div>
          <div className="cap">
            A bad card gets drilled for weeks before you notice — this is where it dies instead.
          </div>
        </div>
      </div>

      <div className="screen" style={{ paddingTop: 4 }}>
        <div>
          <div className="bar"><div style={{ width: `${cards.length ? (keptCount / cards.length) * 100 : 0}%` }} /></div>
          <div className="cap tnum" style={{ marginTop: 6 }}>{keptCount} of {cards.length} kept</div>
        </div>

        {Object.entries(byTopic).map(([path, group]) => (
          <div key={path} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
              <span className="heading">{path.split("::").pop()}</span>
              <button className="cap" style={{ minHeight: 44, color: "var(--accent)", fontWeight: 620 }}
                onClick={() => setPicked((current) => {
                  const next = new Set(current);
                  group.forEach((card) => next.add(card.card_uuid));
                  return next;
                })}>
                Select all {group.length}
              </button>
            </div>
            {group.map((card) => (
              <div key={card.card_uuid} className="rowcard"
                style={{
                  padding: "12px 14px", display: "flex", gap: 10,
                  borderColor: picked.has(card.card_uuid) ? "var(--accent)" : undefined,
                }}>
                <input type="checkbox" checked={picked.has(card.card_uuid)}
                  onChange={() => toggle(card.card_uuid)}
                  style={{ width: 18, height: 18, marginTop: 4, accentColor: "var(--accent)" }} />
                <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 4 }}>
                  <span style={{ fontWeight: 620 }}>{card.rendered_front || card.front}</span>
                  {card.back && <span className="sec">{card.back}</span>}
                  {card.downgraded && (
                    <span className="pill pill-warn">cloze had no deletion — sent as basic</span>
                  )}
                  <div style={{ display: "flex", gap: 4 }}>
                    {!card.reviewed ? (
                      <button className="btn btn-ghost btn-small" onClick={() => keep([card.card_uuid])}>
                        Keep
                      </button>
                    ) : (
                      <span className="pill pill-neutral">kept</span>
                    )}
                    <button className="btn btn-ghost btn-small" onClick={() => setEditing(card)}>Edit</button>
                    <button className="btn btn-ghost btn-small" disabled={busy === card.card_uuid}
                      onClick={() => reroll(card)}>
                      {busy === card.card_uuid ? "Asking again…" : "Re-roll"}
                    </button>
                    <button className="btn btn-danger btn-small" onClick={() => reject([card.card_uuid])}>
                      Reject
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        ))}

        {cards.length > 0 && job && (
          <div className="card" style={{ padding: 20, display: "flex", flexDirection: "column", gap: 8 }}>
            <div className="heading">{cards.length} cards ready</div>
            <button className="btn btn-primary" onClick={studyNow} disabled={busy === "study"}>
              Study these now
            </button>
            <button className="btn btn-ghost" onClick={() => setDownloading(true)}>
              <Icon name="download" size={16} /> Download for Anki (.apkg)
            </button>
            <button className="btn btn-ghost" onClick={() => navigate(`/deck/${job.deck_id}`)}>
              Later
            </button>
          </div>
        )}
      </div>

      {picked.size > 0 && (
        <div className="bulkbar">
          <span className="sec tnum" style={{ fontWeight: 620 }}>{picked.size} selected</span>
          <button className="btn btn-primary" onClick={() => keep([...picked])} disabled={busy === "keep"}>
            Keep {picked.size}
          </button>
          <button className="btn btn-danger" onClick={() => reject([...picked])}>
            Reject {picked.size}
          </button>
        </div>
      )}

      {editing && (
        <EditSheet card={editing} onClose={() => setEditing(null)}
          onSaved={(front, back) => {
            setCards((current) =>
              current.map((c) => (c.card_uuid === editing.card_uuid ? { ...c, front, back, rendered_front: c.note_type === "cloze" ? c.rendered_front : front } : c)));
            setEditing(null);
            toast("Card updated");
          }} />
      )}
      {downloading && job && (
        <DownloadSheet jobId={id} deckName={job.deck_name || "deck"} onClose={() => setDownloading(false)} />
      )}
    </div>
  );
}

function DownloadSheet({ jobId, deckName, onClose }) {
  const toast = useToast();
  const [diff, setDiff] = useState(undefined);
  const [info, setInfo] = useState(null);
  const [skipped, setSkipped] = useState(() => new Set());

  useEffect(() => {
    api(`/api/jobs/${jobId}/diff`).then(setDiff).catch(() => setDiff(null));
    api(`/api/jobs/${jobId}/download-info`).then(setInfo).catch(() => {});
  }, [jobId]);

  const get = async () => {
    const name = deckName.replace(/[^\w\- ]+/g, "").trim() || "deck";
    const skip = [...skipped].map((uuid) => `skip=${encodeURIComponent(uuid)}`).join("&");
    try {
      await download(`/api/jobs/${jobId}/deck.apkg${skip ? `?${skip}` : ""}`, `${name}.apkg`);
      onClose();
    } catch (problem) {
      toast(problem.message);
    }
  };

  return (
    <Sheet onClose={onClose}>
      <div className="heading">Download for Anki</div>
      {diff === undefined && <Skeleton h={40} />}
      {diff === null && (
        <div className="sec">Everything in this download is new to your collection.</div>
      )}
      {diff && (
        <>
          <div className="sec tnum">
            {diff.counts.add} new · {diff.counts.update - skipped.size} updated ·{" "}
            {diff.counts.unchanged} left alone
          </div>
          {diff.updates.length > 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 8, maxHeight: 260, overflowY: "auto" }}>
              {diff.updates.map((update) => (
                <label key={update.card_uuid} className="rowcard"
                  style={{ padding: "10px 12px", display: "flex", gap: 10, cursor: "pointer" }}>
                  <input type="checkbox" checked={!skipped.has(update.card_uuid)}
                    onChange={() => setSkipped((current) => {
                      const next = new Set(current);
                      next.has(update.card_uuid) ? next.delete(update.card_uuid) : next.add(update.card_uuid);
                      return next;
                    })}
                    style={{ accentColor: "var(--accent)" }} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: "var(--type-secondary)", fontWeight: 620 }}>
                      {update.proposed_front}
                    </div>
                    {update.existing_back !== update.proposed_back && (
                      <div className="cap">
                        was: {update.existing_back} → now: {update.proposed_back}
                      </div>
                    )}
                  </div>
                </label>
              ))}
            </div>
          )}
        </>
      )}
      {info && <div className="cap">{info.import_advice}</div>}
      <button className="btn btn-primary" onClick={get}>Download the deck</button>
    </Sheet>
  );
}
