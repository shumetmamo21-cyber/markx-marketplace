"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { browserApi, errorCode } from "@/lib/api/browser";
import { apiErrorText, type Messages } from "@/lib/i18n";

// The shop takes its own photo down (D-062); the API checks the role and
// that the photo is the shop's and still up.
export function WithdrawPhotoButton({ sellerId, imageId, t }: { sellerId: string; imageId: string; t: Pick<Messages, "seller" | "apiErrors"> }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  return (
    <div className="space-y-1">
      <button
        type="button"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          setProblem(null);
          const { error } = await browserApi.POST("/api/v1/seller/{seller_id}/photos/{image_id}/withdraw", {
            params: { path: { seller_id: sellerId, image_id: imageId } },
          });
          setBusy(false);
          if (error) setProblem(apiErrorText(t, errorCode(error)));
          else router.refresh();
        }}
        className="min-h-12 rounded-card border border-clay px-4 text-sm font-semibold text-clay disabled:opacity-60"
      >
        {t.seller.photoWithdraw}
      </button>
      {problem ? <p role="alert" className="text-sm font-semibold text-clay">{problem}</p> : null}
    </div>
  );
}
