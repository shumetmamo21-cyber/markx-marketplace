"use client";

import { ErrorPanel } from "@/components/Resilience";

// A seller dashboard screen that fails: inside the shop's own frame.
// In the page's language; it never shows the error (D-100).
export default function SectionError({ retry }: { error: unknown; retry: () => void }) {
  return <ErrorPanel retry={retry} home="seller" inside />;
}
