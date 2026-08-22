import { createClient } from "@supabase/supabase-js";

// Read at build time. The anon key is meant to be public — it identifies the
// project and nothing else; what actually authorises a request is the signed
// token the provider issues after somebody proves who they are.
const URL = import.meta.env.VITE_SUPABASE_URL;
const ANON_KEY = import.meta.env.VITE_SUPABASE_ANON_KEY;

export const configured = Boolean(URL && ANON_KEY);

export const supabase = configured
  ? createClient(URL, ANON_KEY, {
      auth: {
        // Kept across reloads, and refreshed before it expires, so a long
        // review session does not end in a 401 half way through.
        persistSession: true,
        autoRefreshToken: true,
        detectSessionInUrl: true,
      },
    })
  : null;

// A token pasted into local storage, used only when no auth project is
// configured. This is not a way in: the server verifies the signature against
// the issuer's published keys either way, so a made-up value gets a 401. It
// exists so the application can be driven locally against a development signing
// key without standing up a whole auth project.
const DEV_TOKEN_KEY = "ai_anki_dev_token";

export async function accessToken() {
  if (!supabase) return window.localStorage.getItem(DEV_TOKEN_KEY);
  const { data } = await supabase.auth.getSession();
  return data.session?.access_token ?? null;
}

export function signInWith(provider) {
  return supabase.auth.signInWithOAuth({
    provider,
    options: { redirectTo: window.location.origin },
  });
}

export function signOut() {
  return supabase.auth.signOut();
}

/**
 * The sign-in methods already attached to this account.
 *
 * Somebody who signed in with Google and later with Apple would arrive as two
 * accounts unless the two are attached deliberately, because Apple's "Hide My
 * Email" hands over a private relay address rather than the one Google knows.
 * Automatic matching is on verified email, and those two addresses are not the
 * same address.
 */
export async function identities() {
  const { data, error } = await supabase.auth.getUserIdentities();
  if (error) throw new Error(error.message);
  return data?.identities ?? [];
}

/** Attach another sign-in method to the account already signed in. */
export async function linkIdentity(provider) {
  const { error } = await supabase.auth.linkIdentity({
    provider,
    options: { redirectTo: window.location.origin },
  });
  if (error) throw new Error(error.message);
}

/**
 * Detach one. Refused when it is the last one, because an account with no way
 * to sign into it is an account nobody can reach — including its owner.
 */
export async function unlinkIdentity(identity) {
  const { error } = await supabase.auth.unlinkIdentity(identity);
  if (error) throw new Error(error.message);
}

/**
 * Every call to our own API, carrying the current token.
 *
 * The token goes in a header rather than a cookie deliberately: another site's
 * page cannot read it to attach it, which makes cross-site request forgery
 * structurally impossible rather than merely defended against.
 *
 * It is fetched per call rather than held in a variable because the client
 * refreshes it in the background, and a copy taken at sign-in would go stale
 * mid-session — which reads to the user as being randomly signed out.
 */
export async function api(path, options = {}) {
  const token = await accessToken();
  const response = await fetch(path, {
    ...options,
    headers: {
      "content-type": "application/json",
      ...(token ? { authorization: `Bearer ${token}` } : {}),
      ...(options.headers || {}),
    },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `${response.status} ${response.statusText}`);
  }
  return response.status === 204 ? null : response.json();
}

/** The same, for multipart uploads, which must not carry a JSON content-type. */
export async function upload(path, body) {
  const token = await accessToken();
  const response = await fetch(path, {
    method: "POST",
    body,
    headers: token ? { authorization: `Bearer ${token}` } : {},
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || "upload failed");
  return payload;
}

/**
 * A URL that downloads a file the API will only serve to a signed-in caller.
 *
 * A plain <a href> cannot carry a header, so the bytes are fetched and handed
 * to the browser as a blob instead. Nothing else works: putting the token in
 * the query string would write a live credential into every server log and
 * every browser history entry it passes through.
 */
export async function download(path, filename) {
  const token = await accessToken();
  const response = await fetch(path, {
    headers: token ? { authorization: `Bearer ${token}` } : {},
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || "download failed");
  }
  const blob = await response.blob();
  const href = window.URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = href;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(href);
}
