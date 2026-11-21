"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

type Suggestion = { name: string; slug: string };

// The search field with product suggestions as the person types (blueprint
// D.8: suggestions from two letters). The form around it still works without
// script; the suggestions are links straight to the product.
export function SearchBox({ lang, query, labels }: { lang: string; query: string; labels: { label: string; placeholder: string; suggestions: string } }) {
  const [value, setValue] = useState(query);
  const [items, setItems] = useState<Suggestion[]>([]);
  const [open, setOpen] = useState(false);
  const typed = useRef(false);

  useEffect(() => {
    const words = value.trim();
    if (!typed.current || words.length < 2) {
      setItems([]);
      return;
    }
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      try {
        const response = await fetch(`/api/v1/search/suggest?q=${encodeURIComponent(words)}&lang=${lang}`, { signal: controller.signal });
        if (response.ok) setItems(((await response.json()) as Suggestion[]).slice(0, 8));
      } catch {
        // A suggestion that does not arrive is no loss: the search still works.
      }
    }, 250);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [value, lang]);

  const shown = open && items.length > 0;
  return (
    <div className="relative min-w-0 flex-1">
      <label htmlFor="q" className="sr-only">{labels.label}</label>
      <input
        id="q"
        name="q"
        type="search"
        value={value}
        onChange={(event) => {
          typed.current = true;
          setValue(event.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        onKeyDown={(event) => {
          if (event.key === "Escape") setOpen(false);
        }}
        placeholder={labels.placeholder}
        autoComplete="off"
        enterKeyHint="search"
        // Only while the list exists: a reference to a missing element is
        // invalid ARIA (axe: aria-valid-attr-value, D-100).
        aria-controls={shown ? "q-suggestions" : undefined}
        className="min-h-12 w-full min-w-0 rounded-card border border-line bg-white px-4 text-base text-ink placeholder:text-slate"
      />
      {shown ? (
        <ul id="q-suggestions" aria-label={labels.suggestions} className="absolute inset-x-0 top-full z-30 mt-1 overflow-hidden rounded-card border border-line bg-white text-ink shadow-lg">
          {items.map((item) => (
            <li key={item.slug}>
              <Link href={`/${lang}/p/${item.slug}`} className="flex min-h-12 items-center px-4 hover:bg-paper focus:bg-paper">{item.name}</Link>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
