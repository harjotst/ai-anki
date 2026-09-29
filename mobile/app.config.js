// app.json is the config; this only refuses to build a release that could
// not sign anybody in. Without the provider's URL and key the app falls back
// to the dev-token path, which the deployed API does not offer — so a
// TestFlight build would open on a sign-in screen whose every button fails.
// Set both on expo.dev as EAS environment variables for "production".
module.exports = ({ config }) => {
  const release = process.env.EAS_BUILD === "true" && process.env.EAS_BUILD_PROFILE === "production";
  const missing = ["EXPO_PUBLIC_SUPABASE_URL", "EXPO_PUBLIC_SUPABASE_ANON_KEY"].filter(
    (name) => !process.env[name]
  );
  if (release && missing.length) {
    throw new Error(`A production build needs ${missing.join(" and ")} set for the "production" environment on expo.dev.`);
  }
  return config;
};
