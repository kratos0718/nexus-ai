"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getMe, isAuthenticated } from "@/lib/auth";
import type { User } from "@/types";

export function useAuth(requireAuth = true) {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!isAuthenticated()) {
      if (requireAuth) router.replace("/login");
      setLoading(false);
      return;
    }
    getMe()
      .then(setUser)
      .catch(() => {
        if (requireAuth) router.replace("/login");
      })
      .finally(() => setLoading(false));
  }, [requireAuth, router]);

  return { user, loading };
}
