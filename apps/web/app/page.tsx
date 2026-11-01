"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { api } from "@/lib/api";

export default function Home() {
  const router = useRouter();

  useEffect(() => {
    let cancelled = false;
    api("/dashboard/auth/session")
      .then(() => {
        if (!cancelled) router.replace("/dashboard");
      })
      .catch(() => {
        if (!cancelled) router.replace("/login");
      });
    return () => {
      cancelled = true;
    };
  }, [router]);

  return (
    <div className="hero">
      <span className="muted">Loading…</span>
    </div>
  );
}
