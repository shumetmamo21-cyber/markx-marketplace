# Outside review of pull requests #14 to #17, before the first real users

**Date:** 26 November 2026. **Reviewed:** `main` at `b6f0429`, with the
complete history. **Read-only:** nothing was changed because of this review.
**Scope:** only problems that could hurt real people: reaching another
person's account, orders, address, phone or shop (guest checkout and the
guest's cancel link included); personal details or gate photos shown to the
wrong people (a shop seeing another shop's customers included); the buying
limits or the 30-day new-account rule being got around; unsafe file uploads
(logos, gate photos, phone photos); anything that could lose data or break
backups. Decision: D-110 in `docs/DECISIONS.md`.

| Pull request | Merged as | What it added (decision) |
| --- | --- | --- |
| #14 | `e1849be` | Ethiopian calendar, order again, price chart, a shop's logo, a shop's customers (D-106) |
| #15 | `5794234` | Total to the door, gate photo, lite mode, photos shrunk on the phone, share cards and QR code (D-107) |
| #16 | `e06bd83` | Guest checkout, limits for new accounts, migration 0024 (D-108) |
| #17 | `b6f0429` | 30 days for new accounts, a guest cancels from the link (D-109) |

Method: the diffs of each merge (`git diff <merge>^1 <merge>`), then the code
they touch as it stands on `b6f0429`, the production nginx files, and the
web pages. Claims below cite files and lines on `b6f0429`. Where something
could not be checked, it says UNKNOWN.

**Ratings:** DEFECT = fix before real users. NOTE = can wait.

## Summary

- **1 DEFECT** (R17-1): on the production server, logo and gate-photo
  uploads larger than about 1 MB are refused by nginx before MarkX sees
  them.
- **No DEFECT found** for: reaching another person's account, orders,
  address, phone or shop; gate photos or personal details shown to the wrong
  people; a shop seeing another shop's customers; unsafe file contents;
  losing data or breaking backups.
- **8 NOTES**, most of them already recorded by the sessions that built the
  features and waiting for the founder's values.

## DEFECT

### R17-1 Logo and gate-photo uploads over about 1 MB are refused on the production server

- **What happens.** The production nginx allows request bodies of 1 MB
  (`infra/production/nginx/nginx.conf:51`, `client_max_body_size 1m`),
  except for one location, "The five routes that take a file"
  (`infra/production/nginx/templates/markx.conf.template:68-77`), which
  allows 21 MB. Its pattern lists the five older upload routes only. The two
  upload routes added by #14 and #15 are not in it:
  `POST /api/v1/seller/{seller_id}/store/logo`
  (`apps/api/markx/sellers/router.py`, `upload_store_logo`) and
  `POST /api/v1/me/addresses/{address_id}/gate-photo`
  (`apps/api/markx/images/router.py`, `set_my_gate_photo`). They fall into
  `location /api/`, so nginx answers 413 to a file over about 1 MB, while
  the API itself accepts 8 MB (`images.max_upload_bytes`, 8,000,000).
- **Who is hurt.** A buyer who tries to add a gate photo, or a shop that
  tries to add its logo, from a phone whose picture stays above about 1 MB:
  the upload fails with an error that does not say why. The phone usually
  shrinks a photo to 1,600 pixels first (`apps/web/src/lib/shrink-photo.ts`),
  which mostly keeps it under 1 MB, but it sends the original unchanged when
  the browser cannot shrink it. How often that happens on real phones is
  UNKNOWN. No personal data leaks and nothing is lost; the feature simply
  fails for some people.
- **Why the tests did not see it.** The browser journeys upload against the
  web app and the API directly, not through nginx.
- **Suggested fix (not made):** add `me/addresses/[^/]+/gate-photo` and
  `seller/[^/]+/store/logo` to that location's pattern, and say "seven
  routes" in its comment. One line.

## NOTES

### N1 A guest's per-number limits rely on a number nobody confirms

Guest limits are counted per phone number and per network address
(`apps/api/markx/orders/service.py:1438-1519`, `place_guest_order`). The
number is not confirmed (the founder's rule, D-108), so a person who types a
different number each time is held only by the per-address limits (3 open
guest orders, 30 tries an hour per address), the bot check and the ETB
50,000 cap per order. A phone that reconnects to the mobile network may get
a new address. The same is true of the 30-day rule: a brand-new account
holder can also order as a guest, and neither counts against the other
(by design, D-108). Recorded in D-108 and F-29; worth watching once real
orders arrive (a count of refusals per limit, F-29, would show it).

### N2 Someone can use another person's number as a guest

Anyone may type a stranger's number in guest checkout. The shop then calls
the stranger (already in "Known problems"). Also, orders placed and
cancelled with that number count against it: three cancellations in 24 hours
pause guest orders from that number for a while (P-109-1), and one open guest
order uses up that number's limit. Each attempt needs the bot check. Nothing
of the stranger's account is touched or shown (verified: guest orders have
no `buyer_user_id`; every account query is keyed by the account's id).

### N3 A shop's customer list groups people by the phone number on the order

`seller_customers` (`apps/api/markx/orders/selectors.py:600-667`) reads only
that shop's own orders (`SellerOrder.seller_id == seller_id`), only those
whose contact the shop may already see (`contact_visible`), and asks for the
"see buyers' contacts" capability. **No shop sees another shop's customers.**
Because a guest's number is not confirmed, a guest who typed an account
holder's number appears in that one shop's list as the same customer (the
name of the latest order is shown). Misleading, not a leak.

### N4 The guest's tracking link is the guest's whole key for 60 days

Whoever holds a guest's link sees the order and, from "ready", the handover
code, and can cancel a part before the shop answers
(`selectors.tracking_view`, `service.cancel_by_guest`). Well protected
otherwise, all verified: a 256-bit keyed signature compared in constant time,
an expiry checked both ways (`service.open_tracking_link`), one answer for
forged, expired and missing; the cancel checks that the part belongs to the
order, that the order is a guest's, that the part is still waiting for the
shop, and locks it; the page sends no referrer (`track/[id]/page.tsx`,
`referrer: "no-referrer"`), is not cached and not indexed; neither nginx nor
the API logs query strings (`nginx.conf:32-40`). P-108-7 is the founder's to
confirm.

### N5 A gate photo is never deleted

"Remove" only unlinks the photo from the address
(`apps/api/markx/images/gate_photos.py`, `remove_gate_photo`); the file stays
in private storage for good (the table is append-only by design, migration
0023), and a shop still sees it for an order already placed with it while
it delivers. There is no way yet to delete an account or its photos. A
replaced shop logo also stays at its unguessable public address. A retention
rule for the founder before many photos exist.

### N6 Guest review step has no rate limit of its own

`POST /checkout/guest/quote` needs no bot check and no rate limit. It reveals
nothing about accounts (it only prices a cart for a typed address); the cost
is server work only. The order itself is limited.

### N7 The 30 days count from when the account was made

`is_brand_new` (`service.py`, P-108-8) counts from `users.created_at`. An
account made long before its first sign-in (by staff, or an invitation) is
not "new" when it first orders. PROVISIONAL, the founder's to confirm.

### N8 The shop's customer list reads every confirmed order of the shop on each request

`seller_customers` loads all of the shop's confirmed seller orders and groups
them in Python before applying `limit`. Correct, but slower as a shop grows.
Not a safety problem.

## What was checked and found sound

- **Guest orders never reach an account.** `orders.buyer_user_id` may be
  empty since 0024, with `ck_orders_one_buyer` (an account or a guest,
  never both). Python comparisons that could match an empty buyer with an
  empty actor are guarded: `open_problem_photo` asserts a signed-in viewer;
  `trust.conflict.refuse_conflict` checks for `None`; `_notify_buyer` skips
  guests. The idempotency key of a guest is scoped to the browser's cart
  secret, so a replay returns only that browser's own order.
- **The guest's cancel** (`cancel_by_guest`): only through a valid link, only
  a guest's order, only a part of that order, only while placed and unpaid,
  under the same lock as the shop's answer.
- **Gate photos** (`gate_photos.py`): a five-minute link signed for one
  viewer (and one order); at fetch, the viewer must still be the buyer, or an
  active member of that order's shop with both order and contact rights,
  while that shop delivers to the door; never staff; every shop view
  audited. The database ties an address's photo to its own buyer (a
  foreign key on photo and owner). Guest orders carry no gate photo.
- **Uploads** (logos, gate photos): the shared check (`clean_upload`), then
  decoded and drawn again as WebP (`core/images.py`): only JPEG, PNG and
  WebP, at most 40 megapixels, decompression bombs refused, no metadata or
  location kept, unguessable keys, served with `no-store` and a sandboxing
  content policy (gate photos). The phone's shrinking is only a saving; the
  server trusts none of it.
- **Seller routes** added (`/customers`, `/store/logo`, the gate-photo link)
  sit under `/seller/{seller_id}` with `require_seller`, and look rows up
  together with the seller's id.
- **Order again** (`service.reorder`) finds only the buyer's own order.
- **Lite mode** returns only to a page of this site (`safeNext`).
- **Backups:** gate photos (private) and current logos (public) are in the
  backup's file list (`backup/references.py`) and in the copy tool;
  migrations 0023 and 0024 only add tables, columns, constraints and
  indexes, and refuse to run backwards; the drill's stand-in authenticator
  waits for a fresh code step (D-107), which changes no data.

## Not checked (UNKNOWN)

- How often real phones send an original photo above 1 MB (R17-1).
- How many customers share one mobile network address in Ethiopia (F-29).
- Anything on a real server: nothing is deployed.
