// Local notifications: the phone tells its owner when a plan or a deck is
// ready. Honest scope for Expo Go: these fire while the app's JS is alive —
// foregrounded, or freshly backgrounded — because only a development build
// with APNs can push to a closed app. The screens observe the transition and
// say so; nothing here polls.
//
// Loaded with require behind a platform gate, not a top-level import: the dev
// server's web/SSR render pass executes module side effects in Node, where
// expo-notifications reaches for window and localStorage and takes the whole
// bundler down with it. The web build never runs this branch.
import { AppState, Platform } from "react-native";

type NotificationsModule = typeof import("expo-notifications");

let Notifications: NotificationsModule | null = null;
if (Platform.OS !== "web") {
  Notifications = require("expo-notifications");
  Notifications!.setNotificationHandler({
    handleNotification: async () => ({
      shouldShowBanner: true,
      shouldShowList: true,
      shouldPlaySound: false,
      shouldSetBadge: false,
    }),
  });
}

let asked = false;

// Asked at upload time, not at launch: the permission dialog lands the moment
// its purpose is obvious — "we'll tell you when this is ready".
export async function askOnce() {
  if (!Notifications || asked) return;
  asked = true;
  try {
    await Notifications.requestPermissionsAsync();
  } catch {}
}

export async function notify(title: string, body: string) {
  // Somebody looking at the app already sees the change a banner would
  // announce; the banner is for the pocket.
  if (!Notifications || AppState.currentState === "active") return;
  try {
    await Notifications.scheduleNotificationAsync({
      content: { title, body },
      trigger: null,
    });
  } catch {}
}
