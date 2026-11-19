"use client";

import { useRouter } from "next/navigation";
import { useId, useState } from "react";

import { errorCode, sendForm } from "@/lib/api/browser";
import { apiErrorText, type Messages } from "@/lib/i18n";

type Props = {
  /** The API route that takes the photo as the multipart field `file`. */
  path: string;
  label: string;
  send: string;
  sent: string;
  t: Pick<Messages, "apiErrors">;
};

// One photo upload (a shop's real photo, or evidence on a problem). The API
// cleans the file, removes its location and camera data, and enforces every
// limit (D-062); this only sends what the person picked and says the answer.
export function PhotoUpload({ path, label, send, sent, t }: Props) {
  const router = useRouter();
  const id = useId();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  return (
    <form
      className="space-y-2"
      onSubmit={async (event) => {
        event.preventDefault();
        const form = event.currentTarget;
        setBusy(true);
        setMessage(null);
        const { ok, body } = await sendForm(path, new FormData(form));
        setBusy(false);
        if (!ok) {
          setMessage({ ok: false, text: apiErrorText(t, errorCode(body)) });
          return;
        }
        form.reset();
        setMessage({ ok: true, text: sent });
        router.refresh();
      }}
    >
      <label htmlFor={`${id}-file`} className="block text-sm font-semibold">{label}</label>
      <input id={`${id}-file`} name="file" type="file" accept="image/jpeg,image/png,image/webp" required className="block w-full max-w-full text-sm file:mr-3 file:min-h-12 file:rounded-card file:border file:border-ink file:bg-white file:px-4 file:font-semibold" />
      <button type="submit" disabled={busy} className="min-h-12 rounded-card bg-ink px-4 font-bold text-paper disabled:opacity-60">{send}</button>
      {message ? <p role={message.ok ? "status" : "alert"} className={message.ok ? "font-semibold" : "font-semibold text-clay"}>{message.text}</p> : null}
    </form>
  );
}
