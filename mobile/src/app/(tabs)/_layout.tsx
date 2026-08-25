// The four tabs, mirroring the web shell's rail: Today, Decks, Leaderboard,
// You. The leaderboard badge is the same signal as the web's — pending
// friend requests, shown as a count, never as urgency.
import { Tabs } from "expo-router";
import React, { useEffect, useState } from "react";
import { cached } from "../../lib/data";
import { font, usePalette } from "../../theme";
import { Icon } from "../../ui";

export default function TabsLayout() {
  const palette = usePalette();
  const [requests, setRequests] = useState(0);

  // Re-checked every minute, with a TTL shorter than the interval so each
  // tick actually asks the server — a request accepted or declined anywhere
  // clears the badge within a minute instead of never.
  useEffect(() => {
    const check = () =>
      cached("/api/friends", 15_000)
        .then((friends: any) => setRequests((friends.incoming || []).length))
        .catch(() => {});
    check();
    const timer = setInterval(check, 60_000);
    return () => clearInterval(timer);
  }, []);

  const screen = (name: string, title: string, icon: string, badge?: number) => (
    <Tabs.Screen
      key={name}
      name={name}
      options={{
        title,
        tabBarIcon: ({ color }) => <Icon name={icon} color={color} />,
        tabBarBadge: badge ? badge : undefined,
      }}
    />
  );

  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: palette.accent,
        tabBarInactiveTintColor: palette.text2,
        tabBarStyle: { backgroundColor: palette.surface, borderTopColor: palette.border },
        tabBarLabelStyle: { ...(font("caption") as object) },
        tabBarBadgeStyle: { backgroundColor: palette.accent, color: palette.onAccent },
      }}
    >
      {screen("index", "Today", "today")}
      {screen("decks", "Decks", "decks")}
      {screen("leaderboard", "Leaderboard", "board", requests)}
      {screen("you", "You", "you")}
    </Tabs>
  );
}
