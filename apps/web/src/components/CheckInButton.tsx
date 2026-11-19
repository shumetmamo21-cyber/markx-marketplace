"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { browserApi } from "@/lib/api/browser";

// One tap to confirm "still in stock, still this price" (blueprint I.5, D-029).
export function CheckInButton({ sellerId, label, doneText }: { sellerId: string; label: string; doneText: string }) {
  const router = useRouter();
  const [done, setDone] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  return (
    <div className="space-y-1">
      <button
        type="button"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          const { data } = await browserApi.POST("/api/v1/seller/{seller_id}/offers/check-in", { params: { path: { seller_id: sellerId } }, body: {} });
          setBusy(false);
          if (data) {
            setDone(data.confirmed);
            router.refresh();
          }
        }}
        className="min-h-12 w-full rounded-card bg-adey px-5 font-bold disabled:opacity-60 sm:w-auto"
      >
        {label}
      </button>
      {done !== null ? <p role="status" className="text-sm font-semibold">{doneText.replace("{count}", String(done))}</p> : null}
    </div>
  );
}
