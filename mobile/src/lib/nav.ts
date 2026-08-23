// Going back, when there may be nothing behind you.
//
// A stack screen is not always reached by pushing onto another: a deep link,
// a notification, or a redirect can make it the first thing on screen. There
// `router.back()` is a no-op that logs an error and leaves somebody stuck
// looking at a back arrow that does nothing — so every back arrow falls back
// to a place that certainly exists.
import { useCallback } from "react";
import { useRouter } from "expo-router";

export function useGoBack(fallback: string = "/") {
  const router = useRouter();
  return useCallback(() => {
    if (router.canGoBack()) router.back();
    else router.replace(fallback as never);
  }, [router, fallback]);
}
