// The pulse of every running upload, shared by the screens that show one.
// While anything is planning or writing, the job list is polled every few
// seconds on the focused screen — so a plan turning ready appears where the
// user already is, not where they last pulled to refresh. Observed
// transitions also raise the local notification and drop the shared cache,
// which is what makes the other tabs correct the moment they focus.
import { useFocusEffect } from "expo-router";
import { useCallback, useRef, useState } from "react";
import { dropCache } from "./data";
import { notify } from "./notify";
import { api } from "./session";

export const PLANNING_STATES = ["uploaded", "converting", "planning"];
export const WRITING_STATES = ["generating", "reviewing"];
export const LIVE_STATES = [...PLANNING_STATES, ...WRITING_STATES];

// A deck this young is still the job's business: no cards yet and a run (or
// a run's failure) still attached. Screens show the run, not an empty shell.
export function deckStillForming(deck: any, jobs: any[] | null): boolean {
  if (deck.card_count > 0) return false;
  return (jobs || []).some(
    (job) => job.deck_id === deck.deck_id && job.state !== "complete" && job.state !== "cancelled"
  );
}

// One announcement per (job, state), however many screens watch.
const announced = new Set<string>();

export function useLiveJobs(): { jobs: any[] | null; pulse: number } {
  const [jobs, setJobs] = useState<any[] | null>(null);
  const [pulse, setPulse] = useState(0);
  const known = useRef<Record<string, string>>({});

  const absorb = useCallback((list: any[]) => {
    let moved = false;
    for (const job of list) {
      const before = known.current[job.job_id];
      known.current[job.job_id] = job.state;
      if (!before || before === job.state) continue;
      moved = true;
      const key = `${job.job_id}:${job.state}`;
      if (announced.has(key)) continue;
      announced.add(key);
      const name = job.deck_name || job.source_filename || "Your upload";
      if (job.state === "plan_ready")
        notify("Plan ready", `${name}: review the topics and approve.`);
      if (job.state === "complete")
        notify("Deck ready", `${name}: every lesson and card is written.`);
      if (job.state === "failed")
        notify("Upload hit a problem", `${name}: open the app to retry.`);
    }
    if (moved) {
      // Something changed state: every cached deck list and count is stale.
      dropCache("/api");
      setPulse((n) => n + 1);
    }
    setJobs(list);
  }, []);

  useFocusEffect(
    useCallback(() => {
      let stopped = false;
      let timer: ReturnType<typeof setTimeout>;
      const tick = async () => {
        try {
          const body = await api("/api/jobs");
          if (stopped) return;
          absorb(body.jobs);
          const live = body.jobs.some((j: any) => LIVE_STATES.includes(j.state));
          timer = setTimeout(tick, live ? 4000 : 30000);
        } catch {
          if (!stopped) timer = setTimeout(tick, 15000);
        }
      };
      tick();
      return () => {
        stopped = true;
        clearTimeout(timer);
      };
    }, [absorb])
  );

  return { jobs, pulse };
}
