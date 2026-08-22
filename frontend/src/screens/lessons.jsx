// The lesson reader. Reading comes before drilling; read state persists
// locally so reopening resumes where the person left off.
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../session";
import { cached } from "../data";
import { ErrorCard, Icon, Sheet, Skeleton } from "../ui";

const readKey = (jobId) => `ai_anki_read:${jobId}`;
const readSet = (jobId) => new Set(JSON.parse(window.localStorage.getItem(readKey(jobId)) || "[]"));
const markRead = (jobId, topicId) => {
  const set = readSet(jobId);
  set.add(topicId);
  window.localStorage.setItem(readKey(jobId), JSON.stringify([...set]));
};

export default function Lessons() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [lessons, setLessons] = useState(null);
  const [jobState, setJobState] = useState(null);
  const [open, setOpen] = useState(0);
  const [sheet, setSheet] = useState(false);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [body, job] = await Promise.all([
        api(`/api/jobs/${id}/lessons`),
        api(`/api/jobs/${id}`),
      ]);
      setLessons(body.lessons);
      setJobState(job.state);
      // Resume where they left off: the first unread lesson.
      const read = readSet(id);
      const firstUnread = body.lessons.findIndex((l) => !read.has(l.topic_id));
      if (firstUnread > 0) setOpen((current) => (current === 0 ? firstUnread : current));
    } catch (problem) {
      // An error is a retryable state — never a silent empty list.
      setError(problem.message);
    }
  }, [id]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (jobState !== "generating") return undefined;
    const timer = setInterval(load, 4000);
    return () => clearInterval(timer);
  }, [jobState, load]);

  if (error)
    return <div className="mode"><div className="screen"><ErrorCard message={error} onRetry={load} /></div></div>;
  if (!lessons)
    return <div className="mode"><div className="screen"><Skeleton h={40} /><Skeleton h={300} /></div></div>;

  if (!lessons.length) {
    if (jobState === "generating")
      return (
        <div className="mode"><div className="screen" style={{ paddingTop: 60 }}>
          <div className="heading">The first lesson is being written</div>
          <div className="sec">You can start reading the moment it lands.</div>
        </div></div>
      );
    // Server-confirmed zero lessons: straight to the cards.
    navigate(`/job/${id}/cards`, { replace: true });
    return null;
  }

  const lesson = lessons[Math.min(open, lessons.length - 1)];
  const read = readSet(id);
  const last = open >= lessons.length - 1 && jobState !== "generating";

  const advance = () => {
    markRead(id, lesson.topic_id);
    if (open < lessons.length - 1) setOpen(open + 1);
    else navigate(`/job/${id}/cards`);
  };

  return (
    <div className="mode">
      <div className="mode-top">
        <button className="iconbtn bare" onClick={() => navigate(-1)} aria-label="Back">
          <Icon name="chevL" />
        </button>
        <div style={{ flex: 1, display: "flex", justifyContent: "center" }}>
          <button onClick={() => setSheet(true)}
            style={{
              display: "flex", alignItems: "center", gap: 6, minHeight: 36,
              background: "var(--sunken)", borderRadius: "var(--radius-pill)", padding: "6px 14px",
            }}>
            <span className="cap tnum" style={{ color: "var(--text)", fontWeight: 620 }}>
              Topic {open + 1} of {lessons.length}{jobState === "generating" ? "+" : ""}
            </span>
            <Icon name="chevD" size={14} style={{ color: "var(--muted)" }} />
          </button>
        </div>
        <span style={{ width: 44 }} />
      </div>
      <div style={{ padding: "0 16px" }}>
        <div className="hairline"><div style={{ width: `${((open + 1) / lessons.length) * 100}%` }} /></div>
      </div>

      <div className="mode-body">
        <div className="screen lesson-body">
          <div className="title">{lesson.deck_path.split("::").pop()}</div>
          <div style={{ fontStyle: "italic" }}>{lesson.in_one_line}</div>

          <div>
            <div className="heading" style={{ marginBottom: 6 }}>Why it matters</div>
            <div>{lesson.why_it_matters}</div>
          </div>

          {lesson.sections.map((section) => (
            <div key={section.heading}>
              <div className="heading" style={{ marginBottom: 6 }}>{section.heading}</div>
              {section.builds_on && (
                <div className="cap" style={{ fontStyle: "italic", marginBottom: 6 }}>
                  Builds on: {section.builds_on}
                </div>
              )}
              <div style={{ whiteSpace: "pre-line" }}>{section.body}</div>
            </div>
          ))}

          {lesson.worked_example && (
            <div className="worked">
              <span className="cap" style={{ letterSpacing: ".06em" }}>WORKED EXAMPLE</span>
              <span style={{ fontWeight: 620 }}>{lesson.worked_example.problem}</span>
              <span style={{ whiteSpace: "pre-line" }}>{lesson.worked_example.walkthrough}</span>
            </div>
          )}

          {lesson.misconceptions?.length > 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <div className="heading">What people get wrong</div>
              {lesson.misconceptions.map((myth) => (
                <div key={myth.belief} className="myth">
                  <span style={{ fontWeight: 620 }}>&ldquo;{myth.belief}&rdquo;</span>
                  <span className="sec" style={{ fontSize: 15, lineHeight: "23px" }}>
                    {myth.why_it_is_wrong}
                  </span>
                </div>
              ))}
            </div>
          )}

          {lesson.check_yourself?.length > 0 && (
            <div>
              <div className="heading" style={{ marginBottom: 6 }}>Check yourself</div>
              <ul style={{ paddingLeft: 20, display: "flex", flexDirection: "column", gap: 6 }}>
                {lesson.check_yourself.map((question) => <li key={question}>{question}</li>)}
              </ul>
            </div>
          )}

          {last && (
            <div className="card" style={{ padding: 20, textAlign: "center" }}>
              <div className="heading">That was the last topic</div>
              <div className="sec" style={{ marginTop: 4 }}>The cards are ready to look over.</div>
            </div>
          )}
        </div>
      </div>

      <div className="mode-bottom" style={{ display: "flex", gap: 8 }}>
        <button className="btn btn-ghost" style={{ flex: 1 }} disabled={open === 0}
          onClick={() => setOpen(open - 1)}>
          Previous
        </button>
        <button className="btn btn-primary" style={{ flex: 1.6 }} onClick={advance}>
          {last ? "Review the cards" : "Mark read · Next"}
        </button>
      </div>

      {sheet && (
        <Sheet onClose={() => setSheet(false)}>
          <div className="heading">Topics</div>
          {lessons.map((entry, index) => (
            <button key={entry.topic_id} className="btn btn-ghost"
              style={{ justifyContent: "space-between", borderColor: index === open ? "var(--accent)" : undefined }}
              onClick={() => { setOpen(index); setSheet(false); }}>
              <span style={{ textAlign: "left" }}>{entry.deck_path.split("::").pop()}</span>
              {read.has(entry.topic_id) && <Icon name="check" size={16} style={{ color: "var(--accent)" }} />}
            </button>
          ))}
          {jobState === "generating" && <div className="cap">writing the next topic…</div>}
        </Sheet>
      )}
    </div>
  );
}

/** A single topic's lesson, reached from deck detail. */
export function DeckLesson() {
  const { id, topicId } = useParams();
  const navigate = useNavigate();
  const [lesson, setLesson] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const { jobs } = await cached("/api/jobs", 60_000);
      const candidates = jobs.filter((job) => job.deck_id === id);
      for (const job of candidates) {
        try {
          setLesson(await api(`/api/jobs/${job.job_id}/topics/${topicId}/lesson`));
          return;
        } catch {
          /* try the next job that built this deck */
        }
      }
      throw new Error("This topic has not been taught yet.");
    } catch (problem) {
      setError(problem.message);
    }
  }, [id, topicId]);

  useEffect(() => { load(); }, [load]);

  if (error)
    return <div className="mode"><div className="screen"><ErrorCard message={error} onRetry={load} /></div></div>;
  if (!lesson)
    return <div className="mode"><div className="screen"><Skeleton h={300} /></div></div>;

  return (
    <div className="mode" style={{ height: "auto", minHeight: "100dvh" }}>
      <div className="mode-top">
        <button className="iconbtn bare" onClick={() => navigate(-1)} aria-label="Back">
          <Icon name="chevL" />
        </button>
        <div className="heading" style={{ flex: 1 }}>{lesson.deck_path.split("::").pop()}</div>
      </div>
      <div className="screen lesson-body" style={{ paddingTop: 4 }}>
        <div style={{ fontStyle: "italic" }}>{lesson.in_one_line}</div>
        <div>{lesson.why_it_matters}</div>
        {lesson.sections.map((section) => (
          <div key={section.heading}>
            <div className="heading" style={{ marginBottom: 6 }}>{section.heading}</div>
            <div style={{ whiteSpace: "pre-line" }}>{section.body}</div>
          </div>
        ))}
        {lesson.worked_example && (
          <div className="worked">
            <span className="cap" style={{ letterSpacing: ".06em" }}>WORKED EXAMPLE</span>
            <span style={{ fontWeight: 620 }}>{lesson.worked_example.problem}</span>
            <span style={{ whiteSpace: "pre-line" }}>{lesson.worked_example.walkthrough}</span>
          </div>
        )}
        {lesson.misconceptions?.map((myth) => (
          <div key={myth.belief} className="myth">
            <span style={{ fontWeight: 620 }}>&ldquo;{myth.belief}&rdquo;</span>
            <span className="sec" style={{ fontSize: 15, lineHeight: "23px" }}>{myth.why_it_is_wrong}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
