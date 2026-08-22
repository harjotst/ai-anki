// You: theme, who you are, how you get back in, and the way out.
import React, { useCallback, useEffect, useState } from "react";
import { configured, identities, linkIdentity, signOut, unlinkIdentity } from "../session";
import { cached } from "../data";
import { applyTheme, themeSetting } from "../theme";
import { ErrorCard, Seg, Skeleton, useToast } from "../ui";

const PROVIDERS = [["google", "Google"], ["apple", "Apple"]];

export default function You() {
  const toast = useToast();
  const [me, setMe] = useState(null);
  const [attached, setAttached] = useState(null);
  const [theme, setTheme] = useState(themeSetting());
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setMe(await cached("/api/me", 300_000));
      if (configured) setAttached(await identities());
      else setAttached([]);
    } catch (problem) {
      setError(problem.message);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  if (error) return <div className="screen"><ErrorCard message={error} onRetry={load} /></div>;
  if (!me || attached === null)
    return <div className="screen"><Skeleton h={60} /><Skeleton h={120} /></div>;

  const have = new Set(attached.map((one) => one.provider));
  const lastOne = attached.length <= 1;

  const act = async (run, doneMessage) => {
    try {
      await run();
      if (doneMessage) toast(doneMessage);
      load();
    } catch (problem) {
      toast(problem.message);
    }
  };

  return (
    <div className="screen">
      <div className="title">You</div>

      <div className="card" style={{ padding: 16 }}>
        <div className="heading">{me.display_name || me.email}</div>
        {me.display_name && <div className="cap">{me.email}</div>}
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <div className="cap" style={{ paddingLeft: 2 }}>Appearance</div>
        <Seg
          options={[["system", "System"], ["light", "Light"], ["dark", "Dark"]]}
          value={theme}
          onChange={(next) => { setTheme(next); applyTheme(next); }}
        />
      </div>

      {configured && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <div className="cap" style={{ paddingLeft: 2 }}>How you sign in</div>
          <p className="cap">
            Connect more than one and any of them gets you to this account. Apple
            can hide your real address behind a relay one, so signing in with it
            separately would otherwise look like a different person.
          </p>
          {PROVIDERS.map(([provider, label]) => {
            const identity = attached.find((one) => one.provider === provider);
            return (
              <div key={provider} className="rowcard"
                style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 14px", minHeight: 56 }}>
                <span style={{ flex: 1, fontWeight: 620 }}>{label}</span>
                <span className="cap">
                  {identity ? identity.identity_data?.email || "connected" : "not connected"}
                </span>
                {identity ? (
                  <button className="btn btn-danger btn-small" disabled={lastOne}
                    title={lastOne ? "This is the only way into your account" : ""}
                    onClick={() => act(() => unlinkIdentity(identity), "Disconnected")}>
                    Disconnect
                  </button>
                ) : (
                  <button className="btn btn-primary btn-small"
                    onClick={() => act(() => linkIdentity(provider))}>
                    Connect
                  </button>
                )}
              </div>
            );
          })}
          {lastOne && (
            <p className="cap">
              The last one cannot be disconnected — an account with no way to
              sign into it is an account nobody can reach, including you.
            </p>
          )}
        </div>
      )}

      <button className="btn btn-ghost" onClick={async () => {
        if (configured) await signOut();
        window.localStorage.removeItem("ai_anki_dev_token");
        window.location.assign("/");
      }}>
        Sign out
      </button>
    </div>
  );
}
