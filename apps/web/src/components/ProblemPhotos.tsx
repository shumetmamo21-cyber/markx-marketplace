import type { components } from "@/lib/api/schema";
import { formatDateTime } from "@/lib/format";
import { fill, type Locale, type Messages } from "@/lib/i18n";
import { codeLabel } from "@/lib/labels";

type Photo = components["schemas"]["ProblemPhotoOut"];

/** Evidence photos on a problem (C-16), each behind a link the API signed
 * for the person reading the page; the link works only for them. */
export function ProblemPhotos({ photos, lang, t }: { photos: Photo[]; lang: Locale; t: Pick<Messages, "orders" | "labels"> }) {
  if (photos.length === 0) return null;
  return (
    <ul className="grid grid-cols-2 gap-2 sm:grid-cols-3">
      {photos.map((photo) => {
        const author = codeLabel(t, "author", photo.author_type);
        const when = formatDateTime(photo.created_at, lang);
        return (
          <li key={photo.id} className="space-y-1">
            <a href={photo.url} target="_blank" rel="noopener" className="block">
              {/* eslint-disable-next-line @next/next/no-img-element -- a private, signed link the API serves, already sized */}
              <img src={photo.url} alt={fill(t.orders.problemPhotoAlt, { author, date: when })} width={photo.width} height={photo.height} className="h-32 w-full rounded-card border border-line bg-white object-contain" />
            </a>
            <p className="text-xs text-slate">{author} · {when}</p>
          </li>
        );
      })}
    </ul>
  );
}
