// The auth provider's client, phone side. The anon key is meant to be
// public — it identifies the project and nothing else; what authorises a
// request is the signed token the provider issues after somebody proves
// who they are. PKCE, because a native app's redirect can be observed and
// a code that needs a locally-held verifier is useless to an observer.
import "react-native-url-polyfill/auto";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { createClient } from "@supabase/supabase-js";

const URL = process.env.EXPO_PUBLIC_SUPABASE_URL;
const ANON_KEY = process.env.EXPO_PUBLIC_SUPABASE_ANON_KEY;

export const configured = Boolean(URL && ANON_KEY);

export const supabase = configured
  ? createClient(URL!, ANON_KEY!, {
      auth: {
        storage: AsyncStorage,
        persistSession: true,
        autoRefreshToken: true,
        // There is no browser URL to detect a session in; the sign-in flow
        // hands the code over explicitly.
        detectSessionInUrl: false,
        flowType: "pkce",
      },
    })
  : null;
