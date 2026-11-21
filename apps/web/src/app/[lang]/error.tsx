"use client";

import { ErrorPanel } from "@/components/Resilience";

// Any page of the site whose own section has no error page, and a section
// frame (the shop, seller or staff layout) that fails itself.
// In the page's language; it never shows the error (D-100).
export default function SectionError({ retry }: { error: unknown; retry: () => void }) {
  return <ErrorPanel retry={retry} home="shop" />;
}
