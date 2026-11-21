"use client";

import { ErrorPanel } from "@/components/Resilience";

// A staff screen that fails: inside the staff menu.
// In the page's language; it never shows the error (D-100).
export default function SectionError({ retry }: { error: unknown; retry: () => void }) {
  return <ErrorPanel retry={retry} home="admin" inside />;
}
