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

export async function accessToken() {
  if (!supabase) return null;
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
