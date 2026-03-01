"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

/**
 * Silently refreshes the dashboard server data every `intervalMs` milliseconds
 * by calling router.refresh() — re-runs the server component fetch without
 * a full page reload.
 */
export default function AutoRefresh({ intervalMs = 30_000 }) {
  const router = useRouter();

  useEffect(() => {
    const id = setInterval(() => router.refresh(), intervalMs);
    return () => clearInterval(id);
  }, [router, intervalMs]);

  return null;
}
