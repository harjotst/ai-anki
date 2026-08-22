// Today: the only question a daily user has — what's due, and is the streak
// safe. The pipeline appears only as an attention strip when a job needs the
// user; the word "runs" does not exist here.
import React, { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { cached, dropCache, dueCounts, heatCells, streakFrom } from "../data";
import { ErrorCard, Icon, Skeleton } from "../ui";

const NEEDS_YOU = {
  plan_ready: (job) => ({ line: "Plan ready", action: "Review plan" }),
  interrupted: (job) => ({ line: "Interrupted", action: "Resume" }),
  failed: (job) => ({ line: job.error || "Failed", action: "Retry" }),
};

export function StreakChip({ activity, now = new Date() }) {
  if (!activity) return null;
  const { streak, banked, covered, studiedToday } = streakFrom(activity.days || [], now);
  if (streak === 0) return null;
  // After 8 pm with nothing done today, the chip flips to outline: status,
  // stated as fact, never a nag.
  const atRisk = !studiedToday && now.getHours() >= 20;
  const coveredNote = covered.length
    ? ` — a rest day covered ${new Date(covered[0]).toLocaleDateString(undefined, { weekday: "long" })}`
    : "";
  return (
    <div
      style={{
        display: "flex", alignItems: "baseline", gap: 6,
        border: `3px solid ${atRisk ? "var(--border-strong)" : "var(--accent)"}`,
        borderRadius: "var(--radius-pill)", padding: "6px 14px",
      }}
      title={coveredNote ? `Day ${streak} held${coveredNote}` : undefined}
    >
      <span className="tnum" style={{ color: atRisk ? "var(--text-2)" : "var(--accent)", fontSize: 14, fontWeight: 620 }}>
        Day {streak}
      </span>
      <span className="cap">
        {atRisk ? "expires 11:59 pm" : banked > 0 ? `· ${banked} rest day${banked > 1 ? "s" : ""}` : ""}
      </span>
    </div>
  );
}

export default function Today() {
  const navigate = useNavigate();
  const [decks, setDecks] = useState(null);
  const [counts, setCounts] = useState({});
  const [activity, setActivity] = useState(null);
  const [attention, setAttention] = useState([]);
  const [writing, setWriting] = useState({});
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [deckList, jobs, act] = await Promise.all([
        cached("/api/decks", 30_000),
        cached("/api/jobs", 30_000),
        cached("/api/me/activity", 60_000),
      ]);
      setDecks(deckList.decks);
      setActivity(act);
      setAttention(jobs.jobs.filter((job) => NEEDS_YOU[job.state]));
      setWriting(
        Object.fromEntries(
          jobs.jobs.filter((j) => ["generating", "planning"].includes(j.state))
            .map((j) => [j.deck_id, j])
        )
      );
      setCounts(await dueCounts(deckList.decks));
    } catch (problem) {
      setError(problem.message);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  if (error) return <div className="screen"><ErrorCard message={error} onRetry={load} /></div>;
  if (!decks)
    return (
      <div className="screen">
        <Skeleton h={72} /><Skeleton h={150} r="var(--radius-lg)" />
        <Skeleton h={56} /><Skeleton h={56} /><Skeleton h={56} />
      </div>
    );

  const totalDue = Object.values(counts).reduce((sum, n) => sum + (n || 0), 0);
  const decksWithDue = Object.values(counts).filter((n) => n > 0).length;
  const weekReviews = (activity?.days || [])
    .filter((d) => Date.now() - new Date(d.day).getTime() < 7 * 86_400_000)
    .reduce((sum, d) => sum + d.reviews, 0);

  const firstRun = decks.length === 0;
  const sorted = [...decks].sort(
    (a, b) => (counts[b.deck_id] || 0) - (counts[a.deck_id] || 0)
  );

  return (
    <div className="screen">
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
        <div>
          <div className="title">Today</div>
          <div className="cap">
            {new Date().toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" })}
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <StreakChip activity={activity} />
          <button className="iconbtn" onClick={() => navigate("/job/new")} aria-label="Add a lecture">
            <Icon name="plus" />
          </button>
        </div>
      </div>

      {firstRun ? (
        <div className="card" style={{ padding: 24, display: "flex", flexDirection: "column", gap: 12 }}>
          <div className="heading">How this works</div>
          <div className="sec">
            Upload a lecture → approve the plan → read the lessons → review the
            cards → study a little every day. The app schedules what to see and
            when; your job is only to show up.
          </div>
          <button className="btn btn-primary" onClick={() => navigate("/job/new")}>
            Upload a lecture
          </button>
        </div>
      ) : (
        <div className="card" style={{ padding: 24 }}>
          {totalDue > 0 ? (
            <>
              <div className="stat-xl tnum">{totalDue}</div>
              <div className="sec" style={{ marginTop: 2 }}>
                cards due · {decksWithDue} deck{decksWithDue === 1 ? "" : "s"}
              </div>
              <button className="btn btn-primary" style={{ marginTop: 16, width: "100%" }}
                onClick={() => navigate("/study/all")}>
                Start reviewing
              </button>
            </>
          ) : (
            <>
              <div className="heading">All clear</div>
              <div className="sec" style={{ marginTop: 2 }}>Nothing is due right now.</div>
              <button className="btn btn-ghost" style={{ marginTop: 16 }}
                onClick={() => navigate("/study/all")}>
                Study ahead
              </button>
            </>
          )}
        </div>
      )}

      {attention.map((job) => {
        const note = NEEDS_YOU[job.state](job);
        return (
          <Link key={job.job_id} to={`/job/${job.job_id}`}
            style={{
              display: "flex", alignItems: "center", gap: 12,
              background: "var(--accent-soft)", borderRadius: "var(--radius-md)",
              padding: "12px 14px", color: "var(--text)", minHeight: 44,
            }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 14, fontWeight: 620 }}>
                {job.deck_name || job.source_filename}
              </div>
              <div className="cap">{note.line}</div>
            </div>
            <span style={{ color: "var(--accent)", fontSize: 14, fontWeight: 620, whiteSpace: "nowrap" }}>
              {note.action}
            </span>
          </Link>
        );
      })}

      {activity && activity.days?.length > 0 && (
        <div className="card" style={{ padding: 16, display: "flex", flexDirection: "column", gap: 12 }}>
          <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
            <span className="heading">Activity</span>
            <span className="cap tnum">{weekReviews} reviews this week</span>
          </div>
          <div className="heatmap">
            {heatCells(activity.days).map((cell) => (
              <div key={cell.day} className={`heat-${cell.level}`} title={`${cell.day}: ${cell.count}`} />
            ))}
          </div>
        </div>
      )}

      {sorted.length > 0 && (
        <div className="list">
          {sorted.map((deck) => (
            <Link key={deck.deck_id} to={`/deck/${deck.deck_id}`} className="navrow">
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: 620 }}>{deck.name}</div>
                <div className="cap">
                  {deck.card_count} cards
                  {deck.shared_with_me ? ` · from ${deck.owner_name}` : ""}
                </div>
              </div>
              {writing[deck.deck_id] ? (
                <span className="pill pill-accent">writing…</span>
              ) : counts[deck.deck_id] > 0 ? (
                <span className="pill pill-accent tnum">{counts[deck.deck_id]} due</span>
              ) : null}
              <span style={{ color: "var(--muted)" }}><Icon name="chevR" size={16} /></span>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
