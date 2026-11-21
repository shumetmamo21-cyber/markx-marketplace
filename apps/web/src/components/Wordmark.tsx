// The honest price tag (blueprint I.3): the X is a tick crossed by a short
// stroke, a mark that says "checked".
export function Wordmark({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center gap-0.5 text-xl font-extrabold tracking-tight">
      <span>Mark</span>
      <svg aria-hidden="true" viewBox="0 0 24 24" className="h-6 w-6" focusable="false">
        <path d="M4 13l5 5L20 6" fill="none" stroke="var(--color-adey)" strokeWidth="3.5" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M6 6l12 12" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
      </svg>
      {/* The drawn X, for screen readers: the mark reads "MarkX". */}
      <span className="sr-only">X, </span>
      <span className="sr-only">{label}</span>
    </span>
  );
}
