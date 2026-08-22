// The auth seam, phone side. Two ways in, same door: a real provider
// session (Supabase), or the local dev server's throwaway token. The
// server verifies either against published keys, so nothing here grants
// anything — this module only decides which token to present.
import AsyncStorage from "@react-native-async-storage/async-storage";
import * as Linking from "expo-linking";
import * as WebBrowser from "expo-web-browser";
import { configured, supabase } from "./supabase";

export const BASE =
  process.env.EXPO_PUBLIC_API_URL ?? "http://127.0.0.1:8080";

const DEV_TOKEN_KEY = "ai_anki_dev_token";
let devToken: string | null = null;

export type SessionKind = "supabase" | "dev" | null;

let currentKind: SessionKind = null;
/** What kind of session the app is on right now — the You screen words
 *  itself differently for the development bypass. */
export const sessionKind = () => currentKind;

// Sign-in state changes reach the gate through here, whichever side they
// come from: the provider's own events, or a dev token appearing.
const listeners = new Set<(kind: SessionKind) => void>();
const notify = (kind: SessionKind) => {
  currentKind = kind;
  listeners.forEach((fn) => fn(kind));
};

export function subscribeSession(fn: (kind: SessionKind) => void) {
  listeners.add(fn);
  return () => void listeners.delete(fn);
}

if (supabase) {
  supabase.auth.onAuthStateChange((_event, session) => {
    // Never let the provider's "no session" overwrite a dev session.
    if (session) notify("supabase");
    else if (!devToken) notify(null);
  });
}

async function fetchDevToken(): Promise<string | null> {
  try {
    const response = await fetch(`${BASE}/dev/token`);
    if (!response.ok) return null;
    const body = await response.json();
    return body.token ?? null;
  } catch {
    return null;
  }
}

/** Restore or establish a session. The provider wins over the bypass. */
export async function loadSession(): Promise<SessionKind> {
  if (supabase) {
    const { data } = await supabase.auth.getSession();
    if (data.session) return (currentKind = "supabase");
  }
  devToken = await AsyncStorage.getItem(DEV_TOKEN_KEY);
  if (!devToken) {
    devToken = await fetchDevToken();
    if (devToken) await AsyncStorage.setItem(DEV_TOKEN_KEY, devToken);
  }
  return (currentKind = devToken ? "dev" : null);
}

export async function accessToken(): Promise<string | null> {
  if (supabase) {
    const { data } = await supabase.auth.getSession();
    if (data.session?.access_token) return data.session.access_token;
  }
  return devToken;
}

export async function signOut() {
  if (supabase) {
    const { data } = await supabase.auth.getSession();
    if (data.session) await supabase.auth.signOut();
  }
  devToken = null;
  await AsyncStorage.removeItem(DEV_TOKEN_KEY);
  notify(null);
}

// --- signing in --------------------------------------------------------

function requireAuth() {
  if (!supabase) throw new Error("Sign-in is not configured in this build.");
  return supabase;
}

export async function signInWithEmail(email: string, password: string) {
  const { error } = await requireAuth().auth.signInWithPassword({ email, password });
  if (error) throw new Error(error.message);
}

/** Returns true when the account is ready, false when the provider sent a
 *  confirmation email first — the caller words that state honestly. */
export async function signUpWithEmail(email: string, password: string) {
  const { data, error } = await requireAuth().auth.signUp({ email, password });
  if (error) throw new Error(error.message);
  return Boolean(data.session);
}

export async function signInWithGoogle() {
  const client = requireAuth();
  // The deep link back into this app — in Expo Go an exp:// URL, in a real
  // build the app scheme. Supabase must have it on the redirect allow-list.
  const redirectTo = Linking.createURL("auth-callback");
  const { data, error } = await client.auth.signInWithOAuth({
    provider: "google",
    options: { redirectTo, skipBrowserRedirect: true },
  });
  if (error) throw new Error(error.message);
  const result = await WebBrowser.openAuthSessionAsync(data.url, redirectTo);
  if (result.type !== "success") return; // the person closed it; not an error
  // The redirect carries either a PKCE code (query) or the session itself
  // (fragment) — which one depends on provider and project settings, so both
  // are handled rather than assumed.
  const url = new URL(result.url);
  const fragment = new URLSearchParams(url.hash.replace(/^#/, ""));
  const oops =
    url.searchParams.get("error_description") || fragment.get("error_description") ||
    url.searchParams.get("error") || fragment.get("error");
  if (oops) throw new Error(oops);
  const code = url.searchParams.get("code");
  if (code) {
    const { error: exchangeError } = await client.auth.exchangeCodeForSession(code);
    if (exchangeError) throw new Error(exchangeError.message);
    return;
  }
  const access_token = fragment.get("access_token");
  const refresh_token = fragment.get("refresh_token");
  if (access_token && refresh_token) {
    const { error: setError } = await client.auth.setSession({ access_token, refresh_token });
    if (setError) throw new Error(setError.message);
    return;
  }
  throw new Error("The sign-in redirect carried no session.");
}

// --- calls ---------------------------------------------------------------

async function call(path: string, options: RequestInit, retrying = false): Promise<Response> {
  const token = await accessToken();
  const response = await fetch(`${BASE}${path}`, {
    ...options,
    headers: {
      "content-type": "application/json",
      ...(token ? { authorization: `Bearer ${token}` } : {}),
      ...((options.headers as Record<string, string>) || {}),
    },
  });
  // A dev token outlives the dev server that signed it; refresh once and
  // retry rather than surfacing a 401 the person can do nothing about.
  // Only for the bypass: the provider refreshes its own tokens.
  if (response.status === 401 && devToken && !retrying) {
    const fresh = await fetchDevToken();
    if (fresh) {
      devToken = fresh;
      await AsyncStorage.setItem(DEV_TOKEN_KEY, fresh);
      return call(path, options, true);
    }
  }
  return response;
}

export async function api(path: string, options: RequestInit = {}) {
  const response = await call(path, options);
  if (!response.ok) {
    const body = await response.json().catch(() => ({} as any));
    throw new Error(body.detail || `${response.status}`);
  }
  return response.status === 204 ? null : response.json();
}

/** Multipart uploads must not carry a JSON content-type. */
export async function upload(path: string, body: FormData) {
  const token = await accessToken();
  const response = await fetch(`${BASE}${path}`, {
    method: "POST",
    body,
    headers: token ? { authorization: `Bearer ${token}` } : {},
  });
  const payload = await response.json().catch(() => ({} as any));
  if (!response.ok) throw new Error(payload.detail || "upload failed");
  return payload;
}

/** A file the API only serves to a signed-in caller, as auth headers for
 *  a native download. */
export async function authHeaders() {
  const token = await accessToken();
  return token ? { authorization: `Bearer ${token}` } : {};
}
