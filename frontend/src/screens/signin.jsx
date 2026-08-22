import React, { useState } from "react";
import { configured, signInWith } from "../session";

export default function SignIn() {
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(null);

  if (!configured)
    return (
      <div className="screen" style={{ maxWidth: 420, paddingTop: 80 }}>
        <h1 className="title">ai-anki</h1>
        <p className="sec" style={{ color: "var(--danger)" }}>Sign-in is not configured.</p>
        <p className="cap">
          Set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY, then rebuild the frontend.
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
    // On success the browser leaves for the provider and comes back signed in.
  };

  return (
    <div className="screen" style={{ maxWidth: 420, paddingTop: 80, gap: 16 }}>
      <div>
        <h1 className="title">ai-anki</h1>
        <p className="sec">Upload what you are studying. Get taught it, then drill it.</p>
      </div>
      <button className="btn btn-primary" onClick={() => start("google")} disabled={!!busy}>
        {busy === "google" ? "Opening Google…" : "Continue with Google"}
      </button>
      <button className="btn btn-ghost" onClick={() => start("apple")} disabled={!!busy}>
        {busy === "apple" ? "Opening Apple…" : "Continue with Apple"}
      </button>
      {error && <p className="sec" style={{ color: "var(--danger)" }}>{error}</p>}
    </div>
  );
}
