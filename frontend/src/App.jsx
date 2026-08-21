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

function Upload({ onStarted }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const send = async (file) => {
    setBusy(true);
    setError(null);
    try {
      const body = new FormData();
      body.append("file", file);
      const response = await fetch("/api/jobs", { method: "POST", body });
      if (!response.ok) throw new Error((await response.json()).detail);
      onStarted((await response.json()).job_id);
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

function CardReview({ jobId }) {
  const [cards, setCards] = useState([]);
  const [info, setInfo] = useState(null);
  const [busy, setBusy] = useState(null);

  const refresh = useCallback(async () => {
    setCards((await api(`/api/jobs/${jobId}/cards`)).cards);
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

  const byTopic = cards.reduce((groups, card) => {
    (groups[card.deck_path] ||= []).push(card);
    return groups;
  }, {});

  return (
    <div className="panel">
      <h2>Read them before they reach your collection</h2>
      <p className="muted">
        Nothing here is in your deck yet. A bad card is worse than a missing one —
        it gets drilled for weeks before you notice.
      </p>

      {Object.entries(byTopic).map(([path, group]) => (
        <section key={path}>
          <h3>
            {path}
            <button
              className="ghost"
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

      {cards.length > 0 && info && (
        <div className="download">
          <a href={`/api/jobs/${jobId}/deck.apkg`} download>
            Download {cards.length} cards
          </a>
          <p className="muted small">{info.import_advice}</p>
          <p className="muted small">
            To undo this batch later, search <code>{info.anki_search}</code> in Anki&apos;s
            Browse screen.
          </p>
        </div>
      )}
    </div>
  );
}

function Card({ card, busy, onSave, onReject, onReroll }) {
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
    <div className="card">
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
  // Which jobs we have already asked to plan. Without this the poll below
  // fires the planning pass again every two seconds — an expensive loop.
  const planning = useRef(new Set());

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
          // "Loading…" forever, so it goes back to the upload screen instead.
          if (String(problem.message).includes("job not found")) {
            planning.current.delete(jobId);
            setJob(null);
            setJobId(null);
            history.replaceState(null, "", "/");
          }
        });
    tick();
    const timer = setInterval(tick, 2000);
    return () => clearInterval(timer);
  }, [jobId]);

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

  if (!person && !jobId) return <SignIn onSignedIn={setPerson} />;
  if (!jobId) return <Upload onStarted={setJobId} />;
  if (!job) return <div className="panel narrow muted">Loading…</div>;

  if (job.state === "failed" || error)
    return (
      <div className="panel narrow">
        <h2>That did not work</h2>
        <p className="error">{job.error || error}</p>
        <button
          onClick={() => {
            setError(null);
            setJob(null);
            setJobId(null);
            history.replaceState(null, "", "/");
          }}
        >
          Start again
        </button>
      </div>
    );

  if (job.plan && ["plan_ready", "uploaded"].includes(job.state))
    return <PlanEditor jobId={jobId} plan={job.plan} onApproved={() => setJob(null)} />;

  if (["complete", "reviewing"].includes(job.state)) return <CardReview jobId={jobId} />;

  return (
    <div className="panel narrow">
      <h2>Working…</h2>
      <p className="muted">
        {job.state === "uploaded"
          ? "Starting…"
          : job.state === "planning"
            ? "Reading your material. This takes about twenty seconds."
            : "Writing cards, about ten seconds per topic."}
      </p>
      <p className="muted small">
        You can close this tab. The link keeps working.
      </p>
    </div>
  );
}
