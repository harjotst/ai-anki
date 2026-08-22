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

  useEffect(() => {
    cached("/api/friends", 60_000)
      .then((friends: any) => setRequests((friends.incoming || []).length))
      .catch(() => {});
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
