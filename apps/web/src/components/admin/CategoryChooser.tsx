import type { FlatCategory } from "@/lib/categories";

/** Step one of a new product: pick the category (a plain GET form). */
export function CategoryChooser({ categories, label, button, lead }: { categories: FlatCategory[]; label: string; button: string; lead: string }) {
  return (
    <form method="get" className="space-y-2">
      <p className="text-slate">{lead}</p>
      <label className="block space-y-1">
        <span className="text-sm font-semibold">{label}</span>
        <select name="category" required className="min-h-12 w-full max-w-md rounded-card border border-line bg-white px-3">
          {categories.map((c) => <option key={c.id} value={c.slug} disabled={!c.is_active}>{c.label}</option>)}
        </select>
      </label>
      <button type="submit" className="min-h-12 rounded-card bg-ink px-5 font-bold text-paper">{button}</button>
    </form>
  );
}
