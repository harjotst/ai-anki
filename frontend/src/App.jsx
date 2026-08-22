import React, { useCallback, useEffect, useRef, useState } from "react";

import {
  api,
  configured,
  download,
  signInWith,
  signOut,
  supabase,
  upload,
} from "./session";

const money = (usd) => `$${Number(usd).toFixed(2)}`;
const thousands = (n) => Number(n).toLocaleString();

// --- sign in -------------------------------------------------------------

function SignIn() {
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(null);

  if (!configured)
    return (
      <div className="panel narrow">
        <h1>ai-anki</h1>
        <p className="error">Sign-in is not configured.</p>
        <p className="muted small">
          Set <code>VITE_SUPABASE_URL</code> and <code>VITE_SUPABASE_ANON_KEY</code>,
          then rebuild the frontend.
        </p>
      </div>
    );

  const start = async (provider) => {
    setBusy(provider);
    setError(null);
    const { error: refused } = await signInWith(provider);
    if (refused) {
      setError(refused.message);
      setBusy(null);
    }
    // On success the browser leaves for the provider and comes back signed in,
    // so there is nothing to do here.
  };

  return (
    <div className="panel narrow">
      <h1>ai-anki</h1>
      <p className="muted">
        Upload what you are studying. Get taught it, then drill it.
      </p>
      <div className="providers">
        <button onClick={() => start("google")} disabled={!!busy}>
          {busy === "google" ? "Opening Google…" : "Continue with Google"}
        </button>
        <button className="ghost" onClick={() => start("apple")} disabled={!!busy}>
          {busy === "apple" ? "Opening Apple…" : "Continue with Apple"}
        </button>
      </div>
      {error && <p className="error">{error}</p>}
    </div>
  );
}

// --- upload --------------------------------------------------------------

function Upload({ decks, onStarted }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  // "" means start a new deck. Named explicitly rather than defaulting to the
  // most recent one: adding a lecture to the wrong deck is expensive to undo.
  const [deckId, setDeckId] = useState("");

  const send = async (file) => {
    setBusy(true);
    setError(null);
    try {
      const body = new FormData();
      body.append("file", file);
      if (deckId) body.append("deck_id", deckId);
      onStarted((await upload("/api/jobs", body)).job_id);
    } catch (problem) {
      setError(problem.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="panel narrow">
      <h2>Upload your material</h2>
      <p className="muted">
        PDF, Word, PowerPoint, Excel, text or images. Scans are fine — they are read
        as images, not run through OCR.
      </p>

      {decks.length > 0 && (
        <label className="field">
          <span>Add to</span>
          <select value={deckId} onChange={(e) => setDeckId(e.target.value)}>
            <option value="">a new deck</option>
            {decks.map((deck) => (
              <option key={deck.deck_id} value={deck.deck_id}>
                {deck.name} ({deck.card_count} cards)
              </option>
            ))}
          </select>
        </label>
      )}
      {deckId && (
        <p className="muted small">
          Cards that improve on ones already in this deck will update them in place
          rather than arriving alongside them.
        </p>
      )}

      <input
        type="file"
        disabled={busy}
        onChange={(e) => e.target.files[0] && send(e.target.files[0])}
      />
      {busy && <p className="muted">Uploading…</p>}
      {error && <p className="error">{error}</p>}
    </div>
  );
}

// --- home: what you already have (item 3) --------------------------------

const STATE_LABEL = {
  uploaded: "Not started",
  planning: "Reading your material",
  plan_ready: "Waiting for you",
  generating: "Writing cards",
  reviewing: "Ready to review",
  complete: "Ready to review",
  interrupted: "Interrupted — reopen to resume",
  failed: "Failed",
};

function Home({ decks, jobs, onOpen, onStarted, onRenamed, onSignOut }) {
  const unfinished = jobs.filter((job) => !["complete", "reviewing"].includes(job.state));

  return (
    <>
      <Upload decks={decks} onStarted={onStarted} />

      {jobs.length > 0 && (
        <div className="panel narrow">
          <h2>Your runs</h2>
          {unfinished.length > 0 && (
            <p className="muted small">
              {unfinished.length} still going or waiting on you. They keep running with
              this tab closed.
            </p>
          )}
          <ul className="rows">
            {jobs.map((job) => (
              <li key={job.job_id}>
                <button className="row" onClick={() => onOpen(job.job_id)}>
                  <span className="row-main">{job.source_filename || "upload"}</span>
                  <span className="muted small">
                    {/* A deck is named after whatever file started it, so the
                        first run in a deck would otherwise say its own name
                        twice. */}
                    {job.deck_name && job.deck_name !== job.source_filename
                      ? `${job.deck_name} · `
                      : ""}
                    {STATE_LABEL[job.state] || job.state}
                    {job.card_count > 0 && ` · ${job.card_count} cards`}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {decks.length > 0 && (
        <div className="panel narrow">
          <h2>Your decks</h2>
          <ul className="rows">
            {decks.map((deck) => (
              <DeckRow key={deck.deck_id} deck={deck} onRenamed={onRenamed} />
            ))}
          </ul>
        </div>
      )}

      <div className="panel narrow signout">
        <button className="ghost" onClick={onSignOut}>
          Sign out
        </button>
      </div>
    </>
  );
}

function DeckRow({ deck, onRenamed }) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(deck.name);

  const save = async () => {
    try {
      await api(`/api/decks/${deck.deck_id}`, {
        method: "PATCH",
        body: JSON.stringify({ name }),
      });
      setEditing(false);
      onRenamed();
    } catch {
      setName(deck.name);
      setEditing(false);
    }
  };

  return (
    <li>
      <div className="row static">
        {editing ? (
          <input
            className="row-main"
            value={name}
            autoFocus
            onChange={(e) => setName(e.target.value)}
            onBlur={save}
            onKeyDown={(e) => e.key === "Enter" && save()}
          />
        ) : (
          <span className="row-main">{deck.name}</span>
        )}
        <span className="muted small">
          {deck.card_count} cards · {deck.job_count} run{deck.job_count === 1 ? "" : "s"}
          {deck.last_exported_at
            ? ` · downloaded ${new Date(deck.last_exported_at * 1000).toLocaleDateString()}`
            : " · never downloaded"}
        </span>
        {!editing && (
          <button className="ghost" onClick={() => setEditing(true)}>
            Rename
          </button>
        )}
      </div>
    </li>
  );
}

// --- the plan checkpoint -------------------------------------------------

function PlanEditor({ jobId, plan, onApproved }) {
  const [topics, setTopics] = useState(plan.topics);
  const [estimate, setEstimate] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api(`/api/jobs/${jobId}/estimate`).then(setEstimate).catch(() => {});
  }, [jobId]);

  const edit = (index, field, value) =>
    setTopics(topics.map((t, i) => (i === index ? { ...t, [field]: value } : t)));

  const approve = async () => {
    setBusy(true);
    setError(null);
    try {
      await api(`/api/jobs/${jobId}/plan`, {
        method: "PUT",
        body: JSON.stringify({ topics }),
      });
      await api(`/api/jobs/${jobId}/generate`, { method: "POST" });
      onApproved();
    } catch (problem) {
      setError(problem.message);
    } finally {
      setBusy(false);
    }
  };

  const total = topics.reduce((sum, t) => sum + Number(t.proposed_card_count || 0), 0);

  return (
    <div className="panel">
      <h2>What we found</h2>
      <p className="muted">
        Nothing has been generated yet. Change anything here first — it is much
        cheaper to fix a plan than a deck.
      </p>

      {estimate && (
        <div className={`estimate ${estimate.within_limit ? "" : "over"}`}>
          <strong>{thousands(estimate.input_tokens)}</strong> tokens ·{" "}
          <strong>{money(estimate.estimated_cost_usd)}</strong> estimated across{" "}
          {estimate.topics} topics
          {!estimate.within_limit && (
            <span className="error">
              {" "}
              — over the {thousands(estimate.token_ceiling)} limit. Remove a file.
            </span>
          )}
        </div>
      )}

      <table>
        <thead>
          <tr>
            <th>Deck path</th>
            <th>Difficulty</th>
            <th>Type</th>
            <th>Cards</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {topics.map((topic, index) => (
            <tr key={topic.topic_id}>
              <td>
                <input
                  value={topic.path}
                  onChange={(e) => edit(index, "path", e.target.value)}
                />
                <div className="muted small">{topic.rationale}</div>
              </td>
              <td>
                <select
                  value={topic.difficulty}
                  onChange={(e) => edit(index, "difficulty", e.target.value)}
                >
                  {["easy", "medium", "hard"].map((d) => (
                    <option key={d}>{d}</option>
                  ))}
                </select>
              </td>
              <td>
                <select
                  value={topic.note_type}
                  onChange={(e) => edit(index, "note_type", e.target.value)}
                >
                  {["basic", "cloze"].map((t) => (
                    <option key={t}>{t}</option>
                  ))}
                </select>
              </td>
              <td>
                <input
                  type="number"
                  min="1"
                  max="60"
                  value={topic.proposed_card_count}
                  onChange={(e) =>
                    edit(index, "proposed_card_count", Number(e.target.value))
                  }
                />
              </td>
              <td>
                <button
                  className="ghost"
                  onClick={() => setTopics(topics.filter((_, i) => i !== index))}
                >
                  Drop
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="actions">
        <span className="muted">
          {topics.length} topics · about {total} cards
        </span>
        <button onClick={approve} disabled={busy || !topics.length}>
          {busy ? "Generating…" : "Approve and generate"}
        </button>
      </div>
      {error && <p className="error">{error}</p>}
    </div>
  );
}

// --- learning it, before drilling it -------------------------------------

function Lessons({ jobId, onReview, stillWriting, expected }) {
  const [lessons, setLessons] = useState(null);
  const [open, setOpen] = useState(0);

  // Polled while the run is still going, because a lesson is readable the
  // moment it is committed. Waiting for the whole job would mean ten minutes of
  // a blank screen on a twenty-four topic document — lessons are the slowest
  // thing a run produces, at roughly ten times the output tokens of a card set.
  useEffect(() => {
    const tick = () =>
      api(`/api/jobs/${jobId}/lessons`)
        .then((body) => setLessons(body.lessons))
        .catch(() => setLessons([]));
    tick();
    if (!stillWriting) return undefined;
    const timer = setInterval(tick, 3000);
    return () => clearInterval(timer);
  }, [jobId, stillWriting]);

  if (!lessons) return <div className="panel narrow muted">Loading…</div>;
  if (!lessons.length)
    return stillWriting ? (
      <div className="panel narrow">
        <h2>Reading your material</h2>
        <p className="muted">
          The first topic is being written now. You can start reading as soon as it
          lands — you do not have to wait for the rest.
        </p>
        <p className="muted small">
          About a minute a topic. You can close this tab; it keeps going.
        </p>
      </div>
    ) : (
      <CardReview jobId={jobId} onDone={onReview} />
    );

  const lesson = lessons[open];

  return (
    <div className="panel">
      <h2>Learn it first</h2>
      <p className="muted">
        The cards are here to keep this in your memory, not to put it there. Read
        the topic, then drill it.
      </p>

      <nav className="topics">
        {lessons.map((entry, index) => (
          <button
            key={entry.topic_id}
            className={index === open ? "topic current" : "topic"}
            onClick={() => setOpen(index)}
          >
            <span className="n">{index + 1}</span>
            {entry.deck_path.split("::").pop()}
          </button>
        ))}
        {stillWriting && (
          <span className="topic pending" aria-live="polite">
            writing {expected ? `${lessons.length} of ${expected}` : "more"}…
          </span>
        )}
      </nav>

      <article className="lesson">
        <p className="lede">{lesson.in_one_line}</p>

        <h3>Why it matters</h3>
        <p>{lesson.why_it_matters}</p>

        {lesson.sections.map((section) => (
          <section key={section.heading}>
            <h3>{section.heading}</h3>
            {section.builds_on && (
              <p className="muted small builds-on">
                Builds on: {section.builds_on}
              </p>
            )}
            {section.body.split("\n\n").map((paragraph, index) => (
              <p key={index}>{paragraph}</p>
            ))}
          </section>
        ))}

        {lesson.worked_example && (
          <section className="worked">
            <h3>Worked example</h3>
            <p className="problem">{lesson.worked_example.problem}</p>
            <p>{lesson.worked_example.walkthrough}</p>
          </section>
        )}

        {lesson.misconceptions.length > 0 && (
          <section>
            <h3>What people get wrong</h3>
            {/* The part a textbook does badly, and the reason a card stops
                being failed for six weeks. */}
            {lesson.misconceptions.map((item) => (
              <div key={item.belief} className="misconception">
                <p className="belief">{item.belief}</p>
                <p className="muted">{item.why_it_is_wrong}</p>
              </div>
            ))}
          </section>
        )}

        {lesson.check_yourself.length > 0 && (
          <section>
            <h3>Check yourself</h3>
            <ul className="checks">
              {lesson.check_yourself.map((question) => (
                <li key={question}>{question}</li>
              ))}
            </ul>
          </section>
        )}
      </article>

      <div className="actions">
        <button
          className="ghost"
          disabled={open === 0}
          onClick={() => setOpen(open - 1)}
        >
          Previous
        </button>
        {open < lessons.length - 1 ? (
          <button onClick={() => setOpen(open + 1)}>
            Next: {lessons[open + 1].deck_path.split("::").pop()}
          </button>
        ) : stillWriting ? (
          <button disabled>Writing the next one…</button>
        ) : (
          <button onClick={onReview}>Review the cards</button>
        )}
        {!stillWriting && (
          <button className="ghost" onClick={onReview}>
            Skip to the cards
          </button>
        )}
      </div>
    </div>
  );
}

// --- the card checkpoint -------------------------------------------------

function CardReview({ jobId, onDone }) {
  const [cards, setCards] = useState([]);
  const [progress, setProgress] = useState({ total: 0, reviewed_count: 0 });
  const [info, setInfo] = useState(null);
  const [busy, setBusy] = useState(null);
  // Cards ticked for a bulk action. A Set, because 164 cards is enough that a
  // per-card boolean re-render is visible.
  const [picked, setPicked] = useState(() => new Set());
  const [confirming, setConfirming] = useState(false);

  const refresh = useCallback(async () => {
    const body = await api(`/api/jobs/${jobId}/cards`);
    setCards(body.cards);
    setProgress({ total: body.total, reviewed_count: body.reviewed_count });
    setPicked(new Set());
  }, [jobId]);

  useEffect(() => {
    refresh();
    api(`/api/jobs/${jobId}/download-info`).then(setInfo).catch(() => {});
  }, [jobId, refresh]);

  const act = async (label, path, options) => {
    setBusy(label);
    try {
      await api(path, options);
      await refresh();
    } finally {
      setBusy(null);
    }
  };

  const toggle = (uuid) =>
    setPicked((current) => {
      const next = new Set(current);
      if (next.has(uuid)) next.delete(uuid);
      else next.add(uuid);
      return next;
    });

  const bulk = (verb) =>
    act(`bulk-${verb}`, `/api/jobs/${jobId}/cards/${verb}`, {
      method: "POST",
      body: JSON.stringify({ card_uuids: [...picked] }),
    });

  const byTopic = cards.reduce((groups, card) => {
    (groups[card.deck_path] ||= []).push(card);
    return groups;
  }, {});

  if (confirming)
    return (
      <DownloadStep jobId={jobId} info={info} onBack={() => setConfirming(false)} />
    );

  return (
    <div className="panel">
      <h2>Read them before they reach your collection</h2>
      <p className="muted">
        Nothing here is in your deck yet. A bad card is worse than a missing one —
        it gets drilled for weeks before you notice.
      </p>

      {progress.total > 0 && (
        <div className="progress">
          <div
            className="bar"
            style={{ width: `${(progress.reviewed_count / progress.total) * 100}%` }}
          />
          <span className="muted small">
            {progress.reviewed_count} of {progress.total} read
          </span>
        </div>
      )}

      {/* Sticky, because the selection is made by scrolling and a bar that
          scrolls away turns a bulk action back into per-card clicking. */}
      <div className={`bulkbar ${picked.size ? "active" : ""}`}>
        <label>
          <input
            type="checkbox"
            checked={picked.size > 0 && picked.size === cards.length}
            onChange={(e) =>
              setPicked(e.target.checked ? new Set(cards.map((c) => c.card_uuid)) : new Set())
            }
          />
          {picked.size ? `${picked.size} selected` : "Select all"}
        </label>
        <button disabled={!picked.size || busy} onClick={() => bulk("accept")}>
          {busy === "bulk-accept" ? "Marking…" : "Keep selected"}
        </button>
        <button
          className="ghost danger"
          disabled={!picked.size || busy}
          onClick={() => bulk("reject")}
        >
          {busy === "bulk-reject" ? "Rejecting…" : "Reject selected"}
        </button>
      </div>

      {Object.entries(byTopic).map(([path, group]) => (
        <section key={path}>
          <h3>
            {path}
            <button
              className="ghost"
              onClick={() =>
                setPicked((current) => {
                  const next = new Set(current);
                  group.forEach((card) => next.add(card.card_uuid));
                  return next;
                })
              }
            >
              Select all {group.length}
            </button>
            <button
              className="ghost danger"
              onClick={() =>
                act(path, `/api/jobs/${jobId}/topics/${group[0].topic_id}/cards`, {
                  method: "DELETE",
                })
              }
            >
              Reject all {group.length}
            </button>
          </h3>
          {group.map((card) => (
            <Card
              key={card.card_uuid}
              card={card}
              busy={busy === card.card_uuid}
              picked={picked.has(card.card_uuid)}
              onPick={() => toggle(card.card_uuid)}
              onSave={(front, back) =>
                act(card.card_uuid, `/api/cards/${card.card_uuid}`, {
                  method: "PATCH",
                  body: JSON.stringify({ front, back }),
                })
              }
              onReject={() =>
                act(card.card_uuid, `/api/cards/${card.card_uuid}`, { method: "DELETE" })
              }
              onReroll={() =>
                act(card.card_uuid, `/api/cards/${card.card_uuid}/reroll`, {
                  method: "POST",
                })
              }
            />
          ))}
        </section>
      ))}

      {cards.length > 0 && (
        <div className="download">
          <button onClick={() => setConfirming(true)}>
            Download {cards.length} cards
          </button>
        </div>
      )}
      {onDone && (
        <button className="ghost" onClick={onDone}>
          Back to your runs
        </button>
      )}
    </div>
  );
}

// --- what downloading would actually do (item 5) -------------------------

function DownloadStep({ jobId, info, onBack }) {
  const [diff, setDiff] = useState(null);
  const [error, setError] = useState(null);
  // Updates the user has chosen NOT to take. Opt-out rather than opt-in: the
  // generated card is the one they just reviewed, so taking it is the default.
  const [skipped, setSkipped] = useState(() => new Set());

  useEffect(() => {
    api(`/api/jobs/${jobId}/diff`)
      .then(setDiff)
      .catch((problem) => setError(problem.message));
  }, [jobId]);

  if (error)
    return (
      <div className="panel">
        <h2>Download</h2>
        <p className="muted">
          This job has no earlier deck to compare against, so everything in it is new.
        </p>
        <button
          className="primary"
          onClick={() => download(`/api/jobs/${jobId}/deck.apkg`, `${jobId.slice(0, 8)}.apkg`)}
        >
          Download the deck
        </button>
        <button className="ghost" onClick={onBack}>
          Back to the cards
        </button>
      </div>
    );

  if (!diff) return <div className="panel narrow muted">Working out what changes…</div>;

  const query = [...skipped].map((uuid) => `skip=${encodeURIComponent(uuid)}`).join("&");
  const path = `/api/jobs/${jobId}/deck.apkg${query ? `?${query}` : ""}`;
  const taking = diff.counts.update - skipped.size;

  return (
    <div className="panel">
      <h2>What this will do to your collection</h2>

      <div className="estimate">
        <strong>{diff.counts.add}</strong> new
        {" · "}
        <strong>{taking}</strong> updated
        {" · "}
        <strong>{diff.counts.unchanged}</strong> left alone
        {skipped.size > 0 && <span className="muted"> ({skipped.size} update skipped)</span>}
      </div>

      <p className="muted small">
        Cards that have not changed are left out of the file entirely, so your own
        edits, tags and scheduling on them survive untouched.
      </p>

      {diff.updates.length > 0 && (
        <>
          <h3>Updates — untick any you would rather keep as they are</h3>
          {diff.updates.map((update) => (
            <div key={update.card_uuid} className="card diff">
              <label>
                <input
                  type="checkbox"
                  checked={!skipped.has(update.card_uuid)}
                  onChange={() =>
                    setSkipped((current) => {
                      const next = new Set(current);
                      if (next.has(update.card_uuid)) next.delete(update.card_uuid);
                      else next.add(update.card_uuid);
                      return next;
                    })
                  }
                />
                Take this update
              </label>
              {update.existing_front === update.proposed_front ? (
                // The common case by far: a revision sharpens the answer and
                // leaves the question alone. Showing the question twice makes
                // the reader hunt for a difference that is not there.
                <>
                  <div className="asked">{update.existing_front}</div>
                  <div className="was">
                    <span className="label muted small">Answer now</span>
                    <div>{update.existing_back}</div>
                  </div>
                  <div className="now">
                    <span className="label muted small">Answer after</span>
                    <div>{update.proposed_back}</div>
                  </div>
                </>
              ) : (
                <>
                  <div className="was">
                    <span className="label muted small">In your collection</span>
                    <div>{update.existing_front}</div>
                    <div className="muted">{update.existing_back}</div>
                  </div>
                  <div className="now">
                    <span className="label muted small">Replacing it with</span>
                    <div>{update.proposed_front}</div>
                    <div className="muted">{update.proposed_back}</div>
                  </div>
                </>
              )}
            </div>
          ))}
        </>
      )}

      {diff.warning && <p className="muted small">{diff.warning}</p>}

      <div className="download">
        <button
          className="primary"
          onClick={() => download(path, `${jobId.slice(0, 8)}.apkg`)}
        >
          Download the deck
        </button>
        {info && (
          <>
            <p className="muted small">{info.import_advice}</p>
            <p className="muted small">
              To undo this batch later, search <code>{info.anki_search}</code> in
              Anki&apos;s Browse screen.
            </p>
          </>
        )}
      </div>
      <button className="ghost" onClick={onBack}>
        Back to the cards
      </button>
    </div>
  );
}

function Card({ card, busy, picked, onPick, onSave, onReject, onReroll }) {
  const [editing, setEditing] = useState(false);
  const [front, setFront] = useState(card.front);
  const [back, setBack] = useState(card.back);

  if (editing) {
    return (
      <div className="card editing">
        <textarea value={front} onChange={(e) => setFront(e.target.value)} />
        <textarea value={back} onChange={(e) => setBack(e.target.value)} />
        <div className="actions">
          <button
            onClick={() => {
              onSave(front, back);
              setEditing(false);
            }}
          >
            Save
          </button>
          <button className="ghost" onClick={() => setEditing(false)}>
            Cancel
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className={`card ${picked ? "picked" : ""} ${card.reviewed ? "read" : ""}`}>
      {onPick && (
        <input
          type="checkbox"
          className="pick"
          checked={!!picked}
          onChange={onPick}
          aria-label="select this card"
        />
      )}
      {/* Rendered, not raw: judging a cloze card from its markup is judging the
          wrong thing. */}
      <div className="front">{card.rendered_front}</div>
      <div className="back muted">{card.back}</div>
      <div className="meta">
        {card.tags.map((tag) => (
          <span key={tag} className="tag">
            {tag}
          </span>
        ))}
        {card.downgraded && (
          <span className="tag warn">cloze had no deletion — sent as basic</span>
        )}
      </div>
      <div className="actions">
        <button className="ghost" onClick={() => setEditing(true)}>
          Edit
        </button>
        <button className="ghost" onClick={onReroll} disabled={busy}>
          {busy ? "Asking again…" : "Re-roll"}
        </button>
        <button className="ghost danger" onClick={onReject}>
          Reject
        </button>
      </div>
    </div>
  );
}

// --- shell ---------------------------------------------------------------

export default function App() {
  // undefined while we are still asking the provider; null once we know there
  // is nobody. Without the three states the sign-in screen flashes on every
  // reload for somebody who is already signed in.
  const [session, setSession] = useState(undefined);
  const [jobId, setJobId] = useState(
    new URLSearchParams(location.search).get("job")
  );
  const [job, setJob] = useState(null);
  const [error, setError] = useState(null);
  // Teaching comes first; the cards are what reinforce it. This flips once the
  // reader is done with the lessons, or says they would rather skip them.
  const [reviewing, setReviewing] = useState(false);
  // What this person already has. Loaded once past the door and refreshed
  // whenever they come back to it: the home screen is the only handle on a run
  // once its tab is gone.
  const [home, setHome] = useState(null);
  // Which jobs we have already asked to plan. Without this the poll below
  // fires the planning pass again every two seconds — an expensive loop.
  const planning = useRef(new Set());

  useEffect(() => {
    if (!supabase) {
      // No auth project configured. A development token in local storage still
      // gets past the door, because the server verifies it properly regardless.
      setSession(
        window.localStorage.getItem("ai_anki_dev_token") ? { local: true } : null
      );
      return undefined;
    }
    supabase.auth.getSession().then(({ data }) => setSession(data.session));
    // Covers the return from the provider, a token refresh, and signing out in
    // another tab.
    const { data } = supabase.auth.onAuthStateChange((_event, next) => setSession(next));
    return () => data.subscription.unsubscribe();
  }, []);

  const loadHome = useCallback(async () => {
    try {
      const [decks, jobs] = await Promise.all([api("/api/decks"), api("/api/jobs")]);
      setHome({ decks: decks.decks, jobs: jobs.jobs });
    } catch {
      // Not signed in yet, which the door below handles.
      setHome(null);
    }
  }, []);

  useEffect(() => {
    if (session && !jobId) loadHome();
  }, [jobId, session, loadHome]);

  const goHome = useCallback(() => {
    setError(null);
    setJob(null);
    setJobId(null);
    history.replaceState(null, "", "/");
    loadHome();
  }, [loadHome]);

  // Polled rather than streamed here for simplicity; the SSE endpoint carries
  // the same state and is what a longer run should watch.
  useEffect(() => {
    if (!jobId) return undefined;
    const tick = () =>
      api(`/api/jobs/${jobId}`)
        .then(setJob)
        .catch((problem) => {
          // A job that no longer exists — a stale link, or one cleared after a
          // failure. Swallowing this leaves the app polling a ghost and showing
          // "Loading…" forever, so it goes back to the home screen instead.
          if (String(problem.message).includes("job not found")) {
            planning.current.delete(jobId);
            goHome();
          }
        });
    tick();
    const timer = setInterval(tick, 2000);
    return () => clearInterval(timer);
  }, [jobId, goHome]);

  // An uploaded job sits there until something starts it. The upload and the
  // planning pass are separate calls on purpose — the upload has to be durable
  // before anything expensive begins — so the client is what joins them.
  useEffect(() => {
    if (!jobId || !job || job.state !== "uploaded" || planning.current.has(jobId)) return;
    planning.current.add(jobId);
    api(`/api/jobs/${jobId}/plan`, { method: "POST" })
      .then(() => api(`/api/jobs/${jobId}`).then(setJob))
      .catch((problem) => setError(problem.message));
  }, [jobId, job]);

  useEffect(() => {
    if (jobId) history.replaceState(null, "", `?job=${jobId}`);
  }, [jobId]);

  if (session === undefined) return <div className="panel narrow muted">Loading…</div>;
  if (!session) return <SignIn />;

  if (!jobId)
    return (
      <Home
        decks={home?.decks || []}
        jobs={home?.jobs || []}
        onOpen={setJobId}
        onStarted={setJobId}
        onRenamed={loadHome}
        onSignOut={async () => {
          await signOut();
          setHome(null);
          history.replaceState(null, "", "/");
        }}
      />
    );

  if (!job) return <div className="panel narrow muted">Loading…</div>;

  if (job.state === "failed" || error)
    return (
      <div className="panel narrow">
        <h2>That did not work</h2>
        <p className="error">{job.error || error}</p>
        <button onClick={goHome}>Back to your runs</button>
      </div>
    );

  if (job.plan && ["plan_ready", "uploaded"].includes(job.state))
    return <PlanEditor jobId={jobId} plan={job.plan} onApproved={() => setJob(null)} />;

  // Generating is not a state to be shown a spinner for. The first lesson is
  // readable long before the last card is written, so the reader opens now and
  // fills in behind the person using it.
  if (["complete", "reviewing", "generating"].includes(job.state))
    return reviewing ? (
      <CardReview jobId={jobId} onDone={goHome} />
    ) : (
      <Lessons
        jobId={jobId}
        onReview={() => setReviewing(true)}
        stillWriting={job.state === "generating"}
        expected={job.plan?.topics?.length}
      />
    );

  return (
    <div className="panel narrow">
      <h2>Working…</h2>
      <p className="muted">
        {job.state === "uploaded"
          ? "Starting…"
          : job.state === "planning"
            ? "Reading your material. This takes about twenty seconds."
            : "Writing cards. Topics run five at a time, so this is about a minute."}
      </p>
      <p className="muted small">
        You can close this tab — it keeps running, and it will be waiting under
        &ldquo;your runs&rdquo; when you come back.
      </p>
      <button className="ghost" onClick={goHome}>
        Back to your runs
      </button>
    </div>
  );
}
