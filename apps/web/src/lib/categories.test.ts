import { describe, expect, it } from "vitest";

import { flattenCategories } from "./categories";

describe("flattenCategories", () => {
  it("lists the tree in order, children under their parent, indented", () => {
    const leaf = (id: string, name: string) => ({ id, slug: id, name, position: 0, is_active: true, children: [] });
    const flat = flattenCategories([{ ...leaf("e", "Electronics"), children: [leaf("p", "Phones"), { ...leaf("a", "Audio"), children: [leaf("h", "Headphones")] }] }, leaf("b", "Books")]);
    expect(flat.map((c) => c.label)).toEqual(["Electronics", "— Phones", "— Audio", "— — Headphones", "Books"]);
    expect(flat.map((c) => c.depth)).toEqual([0, 1, 1, 2, 0]);
  });
});
