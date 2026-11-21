"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { browserApi, errorCode } from "@/lib/api/browser";
import { apiErrorText, type Messages } from "@/lib/i18n";

import { ProblemNotice } from "./Resilience";

// The shop takes its own photo down (D-062); the API checks the role and
// that the photo is the shop's and still up.
export function WithdrawPhotoButton({ sellerId, imageId, t }: { sellerId: string; imageId: string; t: Pick<Messages, "seller" | "apiErrors"> }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<{ code: string; text: string } | null>(null);
  const withdraw = async () => {
    setBusy(true);
    setProblem(null);
    const { error } = await browserApi.POST("/api/v1/seller/{seller_id}/photos/{image_id}/withdraw", {
      params: { path: { seller_id: sellerId, image_id: imageId } },
    });
    setBusy(false);
    if (error) setProblem({ code: errorCode(error), text: apiErrorText(t, errorCode(error)) });
    else router.refresh();
  };
  return (
    <div className="space-y-1">
      <button
        type="button"
        disabled={busy}
        onClick={withdraw}
        className="min-h-12 rounded-card border border-clay px-4 text-sm font-semibold text-clay disabled:opacity-60"
      >
        {t.seller.photoWithdraw}
      </button>
      {problem ? <ProblemNotice code={problem.code} text={problem.text} retry={() => void withdraw()} busy={busy} className="text-sm font-semibold text-clay" /> : null}
    </div>
  );
}
