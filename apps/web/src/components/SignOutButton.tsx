"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { browserApi, errorCode, isConnectionProblem } from "@/lib/api/browser";

import { ProblemNotice } from "./Resilience";

// Signing out must reach the server, which ends the session: when the
// connection fails, the person is told so and stays where they are, rather
// than being sent to the home page still signed in (D-100). Any answer from
// the API (an expired session too) leads home as before.
export function SignOutButton({ label, home }: { label: string; home: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState("");
  const signOut = async () => {
    setBusy(true);
    setFailed("");
    const { error } = await browserApi.POST("/api/v1/auth/sign-out", {});
    setBusy(false);
    if (error && isConnectionProblem(errorCode(error))) return setFailed(errorCode(error));
    router.replace(home);
    router.refresh();
  };
  return (
    <div className="space-y-1">
      <button type="button" disabled={busy} onClick={signOut} className="min-h-12 rounded-card border border-ink px-5 font-semibold disabled:opacity-60">
        {label}
      </button>
      {failed ? <ProblemNotice code={failed} retry={() => void signOut()} busy={busy} className="text-sm font-semibold text-clay" /> : null}
    </div>
  );
}
