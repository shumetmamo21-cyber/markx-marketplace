"use client";

import { ErrorPanel } from "@/components/Resilience";

// A storefront or buyer page that fails: inside the shop's header and footer.
// In the page's language; it never shows the error (D-100).
export default function SectionError({ retry }: { error: unknown; retry: () => void }) {
  return <ErrorPanel retry={retry} home="shop" inside />;
}
