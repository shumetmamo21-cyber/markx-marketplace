import { errorCode } from "@/lib/api/browser";
import { fill, type Messages } from "@/lib/i18n";

/** The words the sign-in form shows for an API error. A code asked for too
 * soon after the last one (D-089) says how many seconds are left. */
export function signInProblem(
  t: Pick<Messages["auth"], "rateLimited" | "resendTooSoon" | "botCheckFailed" | "failed">,
  error: unknown,
): string {
  const code = errorCode(error);
  if (code === "otp_resend_too_soon") {
    const seconds = retryAfterSeconds(error);
    if (seconds !== null) return fill(t.resendTooSoon, { seconds });
    return t.rateLimited;
  }
  if (code === "rate_limited") return t.rateLimited;
  if (code === "bot_check_failed") return t.botCheckFailed;
  return t.failed;
}

function retryAfterSeconds(error: unknown): number | null {
  if (!error || typeof error !== "object" || !("error" in error)) return null;
  const details = (error as { error?: { details?: { retry_after_seconds?: unknown } } }).error?.details;
  const value = details?.retry_after_seconds;
  return typeof value === "number" && Number.isInteger(value) && value > 0 && value <= 3600 ? value : null;
}
