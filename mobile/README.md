# ai-anki for iPhone

The phone app: Expo (SDK 57), React Native, TypeScript, Expo Router. One screen
shows what is due today and your decks; from there you upload a document, approve
its plan, read the lessons and study the cards.

## Running it

```bash
npm install
```

```bash
npx expo run:ios
```

It reads three variables from `mobile/.env`:

| Variable | What it is |
|---|---|
| `EXPO_PUBLIC_API_URL` | The API. Leave it unset to use the local dev server. |
| `EXPO_PUBLIC_SUPABASE_URL` | The Supabase project URL. |
| `EXPO_PUBLIC_SUPABASE_ANON_KEY` | The Supabase publishable (anon) key. |

Without the Supabase pair the app signs in with the local dev server's throwaway
token, which only a local server issues.

## Shipping it

Builds go through EAS to TestFlight; the runbook is in
[`docs/operations.md`](../docs/operations.md#shipping-the-ios-app-to-testflight).

```bash
npx eas-cli@latest build -p ios --profile production --auto-submit
```

CI typechecks the app on every push:

```bash
npx tsc --noEmit
```
