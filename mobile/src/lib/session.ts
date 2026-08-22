// The auth seam, phone side. The server holds the actual door: whatever
// token this module produces is verified against the issuer's published
// keys, so nothing here grants anything.
//
// Development: the dev server publishes a signed throwaway token at
// /dev/token, which is fetched automatically — the simulator signs in the
// way the web harness does, with nobody pasting anything. Production:
// Supabase native sign-in lands here later, behind the same accessToken().
import AsyncStorage from "@react-native-async-storage/async-storage";

export const BASE =
  process.env.EXPO_PUBLIC_API_URL ?? "http://127.0.0.1:8080";

const DEV_TOKEN_KEY = "ai_anki_dev_token";
let token: string | null = null;

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

/** Restore or establish a session. True when signed in. */
export async function loadSession(): Promise<boolean> {
  token = await AsyncStorage.getItem(DEV_TOKEN_KEY);
  if (token) return true;
  token = await fetchDevToken();
  if (token) await AsyncStorage.setItem(DEV_TOKEN_KEY, token);
  return Boolean(token);
}

export async function signOut() {
  token = null;
  await AsyncStorage.removeItem(DEV_TOKEN_KEY);
}

async function call(path: string, options: RequestInit, retrying = false): Promise<Response> {
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
  if (response.status === 401 && !retrying) {
    const fresh = await fetchDevToken();
    if (fresh) {
      token = fresh;
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
  const response = await fetch(`${BASE}${path}`, {
    method: "POST",
    body,
    headers: token ? { authorization: `Bearer ${token}` } : {},
  });
  const payload = await response.json().catch(() => ({} as any));
  if (!response.ok) throw new Error(payload.detail || "upload failed");
  return payload;
}
