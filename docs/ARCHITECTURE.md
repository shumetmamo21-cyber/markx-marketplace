# Architecture

## Workspace shape

`apps/*` are deployables. `packages/*` are internal libraries, consumed as
TypeScript source rather than as built output — the Next.js bundler compiles
them via `transpilePackages`. This avoids a build-order dependency between
packages during development. The trade-off: any new app that consumes a
package must also list it in `transpilePackages`.

## Data model

Defined in `packages/db/prisma/schema.prisma`.

```
User ──1:1── SellerProfile ──1:N── Product ──1:N── ProductImage
 │                  │                  │
 │                  │                  ├──1:N── Review
 │                  │                  └──1:N── CartItem
 ├──1:N── Address   │
 ├──1:1── Cart ─────┼──1:N── CartItem
 └──1:N── Order ────┴──1:N── OrderItem

Category ──self-referencing tree──> Category
         ──1:N──> Product
```

### Decisions worth knowing

**Money as integer minor units.** Every amount is an `Int` of minor units plus
a currency code. Floats accumulate rounding error across cart lines, tax and
commission; integers do not. Arithmetic goes through `@markx/shared`.

**Commission in basis points.** `SellerProfile.commissionBps` is an integer —
`250` means 2.50%. Same reasoning as money.

**Order items snapshot the product.** `OrderItem` copies the title and unit
price at purchase time. Sellers edit and delete products; a past order must
still render exactly as it was bought. `productId` is nullable with
`onDelete: SetNull` so deleting a product cannot erase order history.

**Roles on the user, not separate tables.** `UserRole` is an enum on `User`.
A seller gains a `SellerProfile`; the account stays one row. Revisit only if
permissions grow beyond three roles.

### Not yet designed

Authentication, payments and payouts, shipping and fulfilment, search and
indexing, and multi-currency per-seller pricing. The schema deliberately
stops short of guessing at these.
