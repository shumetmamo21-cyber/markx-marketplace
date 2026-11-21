"use client";

import { ErrorPanel } from "@/components/Resilience";

// The seller area when its own frame fails, and the seller start page.
// In the page's language; it never shows the error (D-100).
export default function SectionError({ retry }: { error: unknown; retry: () => void }) {
  return <ErrorPanel retry={retry} home="seller" />;
}
