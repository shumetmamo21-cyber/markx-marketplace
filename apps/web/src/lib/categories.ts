type Node = { id: string; slug: string; name: string; position: number; is_active: boolean; children: Node[] };

export type FlatCategory = { id: string; slug: string; name: string; label: string; depth: number; position: number; is_active: boolean };

/** The category tree as one list in display order, each name indented by its
 * depth ("Phones" under "Electronics" reads "— Phones"), for lists and
 * choosers. */
export function flattenCategories(nodes: Node[], depth = 0): FlatCategory[] {
  return nodes.flatMap((node) => [
    { id: node.id, slug: node.slug, name: node.name, label: `${"— ".repeat(depth)}${node.name}`, depth, position: node.position, is_active: node.is_active },
    ...flattenCategories(node.children, depth + 1),
  ]);
}
