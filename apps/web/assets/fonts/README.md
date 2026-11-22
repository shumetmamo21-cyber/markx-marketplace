# Fonts for the share cards (S-10, D-107)

The share-card pictures (`/[lang]/s/[slug]/card`, `/[lang]/p/[slug]/card`) are
drawn on the server, which has no fonts of its own; Amharic needs an Ethiopic
font or it comes out as empty boxes. These two files are Noto Sans Ethiopic
Bold (the Ethiopic and the Latin parts), unchanged from the npm package
`@fontsource/noto-sans-ethiopic` 5.3.0, under the SIL Open Font License 1.1
(`OFL-LICENSE.txt`, copied from the same package). They are read at start-up
and never sent to the browser.

| File | SHA-256 |
| --- | --- |
| `noto-sans-ethiopic-ethiopic-700-normal.woff` | `4141c5eb45017c91d6eae5794049e40a8f7ca8b8e8c55ec6e41d29d204433ba0` |
| `noto-sans-ethiopic-latin-700-normal.woff` | `6d0e2b48225a63c0c0366b74dafb5c89b7b26974cc10795d582a29b000056c7b` |
| `OFL-LICENSE.txt` | `3ffc81d38a5445271ce8e18ecc31fb1610e9fb8ee21b6fd1f09eb1b1ccc48651` |
