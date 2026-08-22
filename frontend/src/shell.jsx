// The app shell: bottom tabs on a phone, a left rail from 768px up.
// Stacks (study, the pipeline, readers) render full-bleed WITHOUT this shell —
// they are modes, not places.
import React, { useEffect, useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { configured, supabase } from "./session";
import { cached } from "./data";
import { Icon } from "./ui";

const TABS = [
  ["/today", "today", "Today"],
  ["/decks", "decks", "Decks"],
  ["/leaderboard", "board", "Leaderboard"],
  ["/you", "you", "You"],
];

function Tab({ to, icon, label, badge }) {
  return (
    <NavLink to={to} className={({ isActive }) => `tab${isActive ? " on" : ""}`}>
      <Icon name={icon} size={22} />
      <span>{label}</span>
      {badge > 0 && <span className="tab-badge tnum">{badge}</span>}
    </NavLink>
  );
}

export default function Shell() {
  const navigate = useNavigate();
  const [pendingFriends, setPendingFriends] = useState(0);

  useEffect(() => {
    cached("/api/friends", 60_000)
      .then((circle) => setPendingFriends(circle.incoming.length))
      .catch(() => {});
  }, []);

  const tabs = TABS.map(([to, icon, label]) => (
    <Tab
      key={to}
      to={to}
      icon={icon}
      label={label}
      badge={to === "/leaderboard" ? pendingFriends : 0}
    />
  ));

  return (
    <div className="app">
      <nav className="rail">
        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "0 12px 14px" }}>
          <div style={{ width: 22, height: 22, borderRadius: "var(--radius-sm)", background: "var(--accent)" }} />
          <span style={{ fontWeight: 650 }}>ai-anki</span>
        </div>
        <button
          className="btn btn-primary"
          style={{ marginBottom: 10, fontSize: "var(--type-secondary)" }}
          onClick={() => navigate("/job/new")}
        >
          <Icon name="plus" size={16} /> New deck
        </button>
        {tabs}
      </nav>
      <div className="app-scroll">
        <Outlet />
      </div>
      <nav className="tabbar">{tabs}</nav>
    </div>
  );
}

/** Session gate. `undefined` is still-loading; `null` is signed out. The dev
 *  token is not a way in — the server verifies every request regardless. */
export function useSession() {
  const [session, setSession] = useState(undefined);
  useEffect(() => {
    // A development token counts as signed in regardless of configuration —
    // the server holds the actual door.
    if (window.localStorage.getItem("ai_anki_dev_token")) {
      setSession({ local: true });
      return undefined;
    }
    if (!configured) {
      setSession(null);
      return undefined;
    }
    supabase.auth.getSession().then(({ data }) => setSession(data.session));
    const { data } = supabase.auth.onAuthStateChange((_event, next) => setSession(next));
    return () => data.subscription.unsubscribe();
  }, []);
  return session;
}
