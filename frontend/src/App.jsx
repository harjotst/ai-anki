import React, { useCallback, useEffect, useRef, useState } from "react";

const api = async (path, options = {}) => {
  const response = await fetch(path, {
    headers: { "content-type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `${response.status} ${response.statusText}`);
  }
  return response.status === 204 ? null : response.json();
};

const money = (usd) => `$${Number(usd).toFixed(2)}`;
const thousands = (n) => Number(n).toLocaleString();

// --- sign in -------------------------------------------------------------

function SignIn({ onSignedIn }) {
  const [token, setToken] = useState("");
  const [error, setError] = useState(null);

  const submit = async (event) => {
    event.preventDefault();
    setError(null);
    try {
      const { person } = await api("/api/session", {
        method: "POST",
        body: JSON.stringify({ token: token.trim() }),
      });
      onSignedIn(person);
    } catch (problem) {
      setError(problem.message);
    }
  };

  return (
    <form className="panel narrow" onSubmit={submit}>
      <h1>ai-anki</h1>
      <p className="muted">Paste the invite link you were sent.</p>
      <input
        value={token}
        onChange={(e) => setToken(e.target.value)}
        placeholder="invite token"
        autoFocus
      />
      <button type="submit" disabled={!token.trim()}>
        Sign in
      </button>
      {error && <p className="error">{error}</p>}
    </form>
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
      const response = await fetch("/api/jobs", { method: "POST", body });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "upload failed");
      onStarted(payload.job_id);
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

function Home({ decks, jobs, onOpen, onStarted, onRenamed }) {
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
                    {job.deck_name} · {STATE_LABEL[job.state] || job.state}
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
        <a className="primary" href={`/api/jobs/${jobId}/deck.apkg`} download>
          Download the deck
        </a>
        <button className="ghost" onClick={onBack}>
          Back to the cards
        </button>
      </div>
    );

  if (!diff) return <div className="panel narrow muted">Working out what changes…</div>;

  const query = [...skipped].map((uuid) => `skip=${encodeURIComponent(uuid)}`).join("&");
  const href = `/api/jobs/${jobId}/deck.apkg${query ? `?${query}` : ""}`;
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
            </div>
          ))}
        </>
      )}

      {diff.warning && <p className="muted small">{diff.warning}</p>}

      <div className="download">
        <a className="primary" href={href} download>
          Download the deck
        </a>
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
  const [person, setPerson] = useState(null);
  const [jobId, setJobId] = useState(
    new URLSearchParams(location.search).get("job")
  );
  const [job, setJob] = useState(null);
  const [error, setError] = useState(null);
  // What this person already has. Loaded once past the door and refreshed
  // whenever they come back to it: the home screen is the only handle on a run
  // once its tab is gone.
  const [home, setHome] = useState(null);
  // Which jobs we have already asked to plan. Without this the poll below
  // fires the planning pass again every two seconds — an expensive loop.
  const planning = useRef(new Set());

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
    if (!jobId) loadHome();
  }, [jobId, person, loadHome]);

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

  if (!person && !jobId && !home)
    return (
      <SignIn
        onSignedIn={(who) => {
          setPerson(who);
          loadHome();
        }}
      />
    );

  if (!jobId)
    return (
      <Home
        decks={home?.decks || []}
        jobs={home?.jobs || []}
        onOpen={setJobId}
        onStarted={setJobId}
        onRenamed={loadHome}
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

  if (["complete", "reviewing"].includes(job.state))
    return <CardReview jobId={jobId} onDone={goHome} />;

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
