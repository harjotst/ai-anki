// The pipeline: upload → plan → review the plan → generate. A transient flow,
// not a place — it ends in the deck, and it renders by the job's actual state,
// including the interrupted and failed branches that used to dead-end.
import React, { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, upload } from "../session";
import { cached, dropCache } from "../data";
import { ErrorCard, Icon, Seg, Skeleton, useToast } from "../ui";

export default function Job() {
  const { id } = useParams();
  return id ? <JobRun jobId={id} /> : <Upload />;
}

// --- upload ------------------------------------------------------------

function Upload() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [decks, setDecks] = useState([]);
  const [deckId, setDeckId] = useState(params.get("deck") || "");
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [over, setOver] = useState(false);
  const [error, setError] = useState(null);
  const inputRef = useRef(null);

  useEffect(() => {
    cached("/api/decks", 60_000)
      .then((body) => setDecks(body.decks.filter((deck) => !deck.shared_with_me)))
      .catch(() => {});
  }, []);

  const send = async () => {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const body = new FormData();
      body.append("file", file);
      if (deckId) body.append("deck_id", deckId);
      const { job_id } = await upload("/api/jobs", body);
      dropCache("/api/jobs");
      navigate(`/job/${job_id}`, { replace: true });
    } catch (problem) {
      setError(problem.message);
      setBusy(false);
      // Reset so choosing the same file again re-fires the change event.
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  return (
    <div className="mode" style={{ height: "auto", minHeight: "100dvh" }}>
      <TopBar title="Add a lecture" />
      <div className="screen" style={{ paddingTop: 4 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <div className="cap" style={{ paddingLeft: 2 }}>Into</div>
          <select className="field" value={deckId} onChange={(e) => setDeckId(e.target.value)}>
            <option value="">A new deck</option>
            {decks.map((deck) => (
              <option key={deck.deck_id} value={deck.deck_id}>
                {deck.name} ({deck.card_count} cards)
              </option>
            ))}
          </select>
          {deckId && (
            <p className="cap">
              Cards that improve on ones already here update them in place rather
              than arriving alongside them.
            </p>
          )}
        </div>

        <div
          className={`dropzone${over ? " over" : ""}`}
          onDragOver={(e) => { e.preventDefault(); setOver(true); }}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setOver(false);
            if (e.dataTransfer.files[0]) setFile(e.dataTransfer.files[0]);
          }}
          onClick={() => inputRef.current?.click()}
          role="button"
        >
          <Icon name="doc" size={28} />
          <span className="sec">Drop a lecture here, or browse</span>
          <span className="cap">PDF, Word, PowerPoint, Excel, text or images — scans are fine</span>
          <input ref={inputRef} type="file" hidden
            onChange={(e) => e.target.files[0] && setFile(e.target.files[0])} />
        </div>

        {file && (
          <div className="rowcard" style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 14px" }}>
            <span style={{ flex: 1, fontWeight: 620, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {file.name}
            </span>
            <span className="cap tnum">{(file.size / 1024 / 1024).toFixed(1)} MB</span>
            <button className="iconbtn bare" onClick={() => setFile(null)} aria-label="Remove file">
              <Icon name="x" size={16} />
            </button>
          </div>
        )}
        {error && <ErrorCard message={error} onRetry={send} />}
        <button className="btn btn-primary" onClick={send} disabled={!file || busy}>
          {busy ? "Uploading…" : "Upload & plan"}
        </button>
      </div>
    </div>
  );
}

// --- a running job -------------------------------------------------------

function JobRun({ jobId }) {
  const navigate = useNavigate();
  const [job, setJob] = useState(null);
  const [error, setError] = useState(null);
  const planFired = useRef(false);

  const refresh = useCallback(async () => {
    try {
      setJob(await api(`/api/jobs/${jobId}`));
      setError(null);
    } catch (problem) {
      if (String(problem.message).includes("not found")) navigate("/today", { replace: true });
      else setError(problem.message);
    }
  }, [jobId, navigate]);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 2000);
    return () => clearInterval(timer);
  }, [refresh]);

  // An uploaded job sits still until something starts it; the client joins
  // the two calls, exactly once.
  useEffect(() => {
    if (!job || job.state !== "uploaded" || planFired.current) return;
    planFired.current = true;
    api(`/api/jobs/${jobId}/plan`, { method: "POST" }).then(refresh).catch((p) => setError(p.message));
  }, [job, jobId, refresh]);

  useEffect(() => {
    if (job?.state === "complete") navigate(`/job/${jobId}/lessons`, { replace: true });
  }, [job, jobId, navigate]);

  if (error) return <Frame title="Upload"><ErrorCard message={error} onRetry={refresh} /></Frame>;
  if (!job) return <Frame title=""><Skeleton h={120} /></Frame>;

  if (["uploaded", "planning"].includes(job.state))
    return (
      <Frame title={job.source_filename || "Planning"}>
        <div className="card" style={{ padding: 24, display: "flex", flexDirection: "column", gap: 8 }}>
          <div className="heading">Reading your material</div>
          <div className="sec">
            Breaking it into topics and judging how much each is worth. You can
            leave — this keeps running.
          </div>
          <div className="hairline" style={{ marginTop: 8 }}><div style={{ width: "30%" }} /></div>
        </div>
      </Frame>
    );

  if (job.state === "plan_ready" && job.plan)
    return <PlanReview job={job} onApproved={refresh} />;

  if (job.state === "generating" || job.state === "reviewing")
    return <Generating job={job} />;

  if (job.state === "interrupted")
    return (
      <Frame title={job.source_filename || "Interrupted"}>
        <div className="card" style={{ padding: 24, display: "flex", flexDirection: "column", gap: 12 }}>
          <div className="heading">Interrupted</div>
          <div className="sec">
            The machine restarted part-way through. Everything already written is
            safe; resuming only runs what is left.
          </div>
          <button className="btn btn-primary"
            onClick={() => api(`/api/jobs/${jobId}/${job.plan ? "generate" : "plan"}`, { method: "POST" })
              .then(refresh)
              .catch((p) => setError(p.message))}>
            Resume
          </button>
        </div>
      </Frame>
    );

  if (job.state === "failed")
    return (
      <Frame title={job.source_filename || "Failed"}>
        <ErrorCard
          message={job.error || "This upload failed."}
          onRetry={() =>
            api(`/api/jobs/${jobId}/clear`, { method: "POST" })
              .catch(() => {})
              .then(() => api(`/api/jobs/${jobId}/${job.plan ? "generate" : "plan"}`, { method: "POST" }))
              .then(refresh)
              .catch((p) => setError(p.message))
          }
        />
      </Frame>
    );

  return <Frame title=""><Skeleton h={120} /></Frame>;
}

function TopBar({ title, caption }) {
  const navigate = useNavigate();
  return (
    <div className="mode-top">
      <button className="iconbtn bare" onClick={() => navigate(-1)} aria-label="Back">
        <Icon name="chevL" />
      </button>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="heading">{title}</div>
        {caption && <div className="cap">{caption}</div>}
      </div>
    </div>
  );
}

function Frame({ title, caption, children }) {
  return (
    <div className="mode" style={{ height: "auto", minHeight: "100dvh" }}>
      <TopBar title={title} caption={caption} />
      <div className="screen" style={{ paddingTop: 4 }}>{children}</div>
    </div>
  );
}

// --- plan review -----------------------------------------------------------

const slug = (text) =>
  text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 40) || "topic";

function PlanReview({ job, onApproved }) {
  const toast = useToast();
  const [topics, setTopics] = useState(job.plan.topics.map((t) => ({ ...t, dropped: false })));
  const [estimate, setEstimate] = useState(undefined); // undefined loading, null failed
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    api(`/api/jobs/${job.job_id}/estimate`).then(setEstimate).catch(() => setEstimate(null));
  }, [job.job_id]);

  const edit = (index, patch) =>
    setTopics((current) => current.map((t, i) => (i === index ? { ...t, ...patch } : t)));

  const kept = topics.filter((t) => !t.dropped);
  const totalCards = kept.reduce((sum, t) => sum + Number(t.proposed_card_count || 0), 0);

  const approve = async () => {
    setBusy(true);
    setError(null);
    try {
      // Drops apply only now — an accidental tap on Remove lost nothing.
      await api(`/api/jobs/${job.job_id}/plan`, {
        method: "PUT",
        body: JSON.stringify({ topics: kept.map(({ dropped, ...topic }) => topic) }),
      });
      await api(`/api/jobs/${job.job_id}/generate`, { method: "POST" });
      dropCache("/api/jobs");
      onApproved();
    } catch (problem) {
      setError(problem.message);
      setBusy(false);
    }
  };

  return (
    <div className="mode" style={{ height: "auto", minHeight: "100dvh", paddingBottom: 88 }}>
      <TopBar title="Plan review" caption={job.source_filename} />
      <div className="screen" style={{ paddingTop: 4 }}>
        <div className="sunken tnum" style={{ padding: "10px 14px", fontSize: "var(--type-secondary)", fontWeight: 620 }}>
          {kept.length} topics · ~{totalCards} cards
          {estimate === undefined ? " · estimating…"
            : estimate === null ? ""
            : ` · est $${estimate.estimated_cost_usd.toFixed(2)}`}
        </div>
        {estimate === null && (
          <div className="cap">Estimate unavailable — you can still generate.</div>
        )}
        {estimate && !estimate.within_limit && (
          <ErrorCard message={`Over the ${estimate.token_ceiling.toLocaleString()}-token limit — remove a file and re-upload.`} />
        )}
        <p className="cap">
          Nothing is generated until you approve. It is much cheaper to fix a
          plan than a deck.
        </p>

        <div className="list">
          {topics.map((topic, index) =>
            topic.dropped ? (
              <div key={topic.topic_id} className="card"
                style={{ padding: 14, opacity: .55, display: "flex", alignItems: "center", gap: 10 }}>
                <span style={{ flex: 1, fontWeight: 620, textDecoration: "line-through", color: "var(--muted)" }}>
                  {topic.path.split("::").pop()}
                </span>
                <button style={{ color: "var(--accent)", fontWeight: 620, minHeight: 44, fontSize: "var(--type-secondary)" }}
                  onClick={() => edit(index, { dropped: false })}>
                  Restore
                </button>
              </div>
            ) : (
              <div key={topic.topic_id} className="card"
                style={{ padding: 14, display: "flex", flexDirection: "column", gap: 10 }}>
                <input className="field" style={{ fontWeight: 620 }} value={topic.path}
                  onChange={(e) => edit(index, { path: e.target.value })} />
                {topic.rationale && <div className="cap">{topic.rationale}</div>}
                <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                  <Seg style={{ flex: "1 1 150px" }}
                    options={[["easy", "easy"], ["medium", "medium"], ["hard", "hard"]]}
                    value={topic.difficulty}
                    onChange={(difficulty) => edit(index, { difficulty })} />
                  <Seg style={{ flex: "1 1 110px" }}
                    options={[["basic", "basic"], ["cloze", "cloze"]]}
                    value={topic.note_type}
                    onChange={(note_type) => edit(index, { note_type })} />
                  <div style={{ display: "flex", alignItems: "center", gap: 2, border: "1px solid var(--border)", borderRadius: "var(--radius-md)", padding: 4 }}>
                    <button className="iconbtn bare" style={{ width: 36, height: 36 }} aria-label="Fewer cards"
                      onClick={() => edit(index, { proposed_card_count: Math.max(1, topic.proposed_card_count - 1) })}>
                      <Icon name="minus" size={14} />
                    </button>
                    <span className="tnum" style={{ fontSize: "var(--type-secondary)", fontWeight: 620, width: 24, textAlign: "center" }}>
                      {topic.proposed_card_count}
                    </span>
                    <button className="iconbtn bare" style={{ width: 36, height: 36 }} aria-label="More cards"
                      onClick={() => edit(index, { proposed_card_count: Math.min(60, topic.proposed_card_count + 1) })}>
                      <Icon name="plus" size={14} />
                    </button>
                  </div>
                  <button style={{ color: "var(--muted)", minHeight: 44, padding: "0 8px", fontSize: "var(--type-secondary)" }}
                    onClick={() => edit(index, { dropped: true })}>
                    Remove
                  </button>
                </div>
              </div>
            )
          )}
          <button className="btn btn-ghost"
            onClick={() => setTopics((current) => [...current, {
              topic_id: `${slug("added")}-${current.length}`,
              path: "New topic",
              difficulty: "medium",
              rationale: "",
              note_type: "basic",
              proposed_card_count: 5,
              claims: [],
              dropped: false,
            }])}>
            <Icon name="plus" size={16} /> Add topic
          </button>
        </div>
        {error && <ErrorCard message={error} />}
      </div>

      <div className="bulkbar">
        <div style={{ flex: 1, maxWidth: 420 }}>
          <div className="tnum" style={{ fontSize: "var(--type-secondary)", fontWeight: 620 }}>
            {kept.length} topics · ~{totalCards} cards
          </div>
          <div className="cap">nothing runs until you approve</div>
        </div>
        <button className="btn btn-primary" onClick={approve} disabled={busy || !kept.length}>
          {busy ? "Starting…" : "Approve & generate"}
        </button>
      </div>
    </div>
  );
}

// --- generating --------------------------------------------------------------

function Generating({ job }) {
  const navigate = useNavigate();
  const [topics, setTopics] = useState([]);
  const [lessonCount, setLessonCount] = useState(0);

  useEffect(() => {
    const tick = () => {
      api(`/api/jobs/${job.job_id}/topics`).then((body) => setTopics(body.topics)).catch(() => {});
      api(`/api/jobs/${job.job_id}/lessons`)
        .then((body) => setLessonCount(body.lessons.length))
        .catch(() => {});
    };
    tick();
    const timer = setInterval(tick, 3000);
    return () => clearInterval(timer);
  }, [job.job_id]);

  const done = topics.filter((t) => t.status === "done").length;
  const current = topics.find((t) => t.status === "running");

  return (
    <Frame title={job.deck_name || job.source_filename} caption="writing lessons and cards">
      <div className="card" style={{ padding: 20, display: "flex", flexDirection: "column", gap: 12 }}>
        <div className="hairline">
          <div style={{ width: `${topics.length ? (done / topics.length) * 100 : 8}%` }} />
        </div>
        <div className="sec tnum">
          {done} of {topics.length || "…"} topics
          {current ? ` · writing ${current.path.split("::").pop()}` : ""}
        </div>
        <div className="cap">You can leave — this keeps running.</div>
      </div>
      <button className="btn btn-primary" disabled={lessonCount === 0}
        onClick={() => navigate(`/job/${job.job_id}/lessons`)}>
        {lessonCount > 0 ? `Read lessons (${lessonCount} ready)` : "The first lesson is being written…"}
      </button>
      <button className="btn btn-ghost" onClick={() => navigate(`/job/${job.job_id}/cards`)}>
        Review the cards written so far
      </button>
    </Frame>
  );
}
