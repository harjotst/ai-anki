# Porting a web screen to the phone

Each mobile screen is a native mirror of one web screen. Same endpoints, same
copy, same information order — different primitives. The web screen is the
spec; when unsure, do what it does.

## Read these first, fully

- `frontend/src/screens/<name>.jsx` — the screen you are porting. Its data
  flow, copy, and edge states carry over verbatim unless a rule below says
  otherwise.
- `mobile/src/app/(tabs)/index.tsx` and `mobile/src/app/study/[deckId].tsx`
  — finished ports. Match their idiom exactly: inline styles from
  `usePalette()`, `T`/`Cap` for text, spacing from `space[n]`.
- `mobile/src/ui/index.tsx` — the primitives. Use them; do not invent
  parallel ones. Available: Icon, T, Cap, Screen, CardBox, Button, IconBtn,
  Pill, NavRow, Seg, Skeleton, ErrorCard, Sheet, CardText, useToast.
- `mobile/src/theme/index.tsx` — usePalette(), font(), space, radius,
  target, useThemeSetting (for the theme picker on You).
- `mobile/src/lib/session.ts` (api, upload, signOut, BASE),
  `mobile/src/lib/data.ts` (cached, dropCache, dueCounts, streakFrom,
  heatCells), `mobile/src/lib/queue.ts`.

## Hard rules

- **No color literal anywhere** — every color comes from `usePalette()`.
  CI greps for hex; one stray literal fails the build.
- Touch targets ≥ 44pt (`target.min`); rating-class actions 48 (`target.rating`).
- Text through `T`/`Cap` (or a style built from `font()`), never a bare
  `<Text>` with hand-picked sizes.
- Navigation: `useRouter()` from expo-router. Routes that exist:
  `/` (Today), `/decks`, `/leaderboard`, `/you`, `/study/[deckId]`
  (`all` chains every deck), `/deck/[id]`, `/compare/[deckId]`,
  `/lessons/[jobId]`. Job/upload screens do NOT exist on mobile yet: where
  the web navigates to `/job/...`, show
  `toast("Finish this on the web for now — job screens land on mobile next.")`.
- Downloads (.apkg export) do not exist on mobile: omit the control entirely
  rather than shipping a dead button.
- Web-only affordances (keyboard hints, hover, copy-to-clipboard via
  navigator) get native equivalents: `Share.share()` from react-native for
  share/copy actions, or omit if there is no equivalent.
- Errors: `ErrorCard` with a Retry wired to the loader. Loading: `Skeleton`
  rows shaped like the content. Empty states keep the web's copy.
- Screens inside the tab bar use `<Screen>` (it scrolls and pads).
  Full-bleed stack screens (deck detail, compare, lessons) manage their own
  ScrollView + `useSafeAreaInsets()` top padding, with a header row:
  back IconBtn (`chevL`), centered `Cap` title, optional right action —
  copy the study screen's header.
- TypeScript must pass `npx tsc --noEmit` (run it from `mobile/`). Screen
  data can be `any`; do not build elaborate types.
- Comment style: sparse, explaining constraints, matching the existing files.
