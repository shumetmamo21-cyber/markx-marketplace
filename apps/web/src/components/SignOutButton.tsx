"use client";

import { useRouter } from "next/navigation";

import { browserApi } from "@/lib/api/browser";

export function SignOutButton({ label, home }: { label: string; home: string }) {
  const router = useRouter();
  return (
    <button
      type="button"
      onClick={async () => {
        await browserApi.POST("/api/v1/auth/sign-out", {});
        router.replace(home);
        router.refresh();
      }}
      className="min-h-12 rounded-card border border-ink px-5 font-semibold"
    >
      {label}
    </button>
  );
}
