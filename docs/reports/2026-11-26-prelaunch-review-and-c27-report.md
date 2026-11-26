# MarkX: pre-launch check and C-27 (26 November 2026)

**For the founder, in plain English.** Repository
`shumetmamo21-cyber/markx-marketplace`, with the complete history. Started
from `main` at `b6f0429`, as expected.

**Nothing was deployed and nothing was paid for.** No server, account, bot,
SMS, storage bucket or cloud resource was created, touched or bought. All
the testing ran on this session's own temporary machine (a local database
in a container) and on GitHub's normal checks.

---

## Part 1: the pre-launch check of pull requests #14, #15, #16 and #17

I read everything those four pull requests changed, as an outside
reviewer. I changed nothing because of it. The full review, with file and
line references, is in
`docs/reports/2026-11-26-prs-14-17-prelaunch-review.md`.

### DEFECT (fix before real users): 1

**R17-1: on the real server, logo and gate-photo uploads above about 1 MB
are refused.**

- **What happens:** the web server that sits in front of MarkX (nginx)
  only accepts files bigger than 1 MB on a fixed list of "upload" routes.
  The list was written before #14 and #15 and still names only the five
  older routes. The two new ones, a shop's logo and a buyer's gate photo,
  were never added.
- **What a person sees:** a bigger photo is refused before MarkX ever sees
  it, with an error that doesn't explain why. MarkX itself would accept up
  to 8 MB.
- **How often:** the phone usually shrinks a photo first, which often
  brings it under 1 MB. When it can't shrink it, the phone sends the
  original. How often that happens on real phones is UNKNOWN.
- **Risk:** no data leaks and nothing is lost; the feature just fails for
  some people.
- **Evidence:** `infra/production/nginx/nginx.conf` line 51 sets 1 MB.
  `infra/production/nginx/templates/markx.conf.template` lines 68–77 hold
  the list of "the five routes that take a file", and neither new route is
  in it.
- **Why no test caught it:** the tests never send uploads through nginx.
- **Fix:** add the two routes to that list, a one-line change. Not made,
  because Part 1 was read-only.

### NOTES (can wait): 8

1. **Guest limits depend on a phone number nobody checks.** Someone who
   types a different number each time is held only by the limits per
   connection (3 open guest orders), the "are you a person" check and the
   ETB 50,000 cap.
   - A phone can sometimes get a new connection address by reconnecting.
   - Someone with a new account can also order as a guest; the two don't
     count against each other. That was your design (D-108).
2. **Someone can type another person's number as a guest.**
   - The shop will then call a stranger.
   - Orders placed and cancelled with that number count against it, so
     repeated cancellations can pause guest orders for that number for a
     while.
   - Nothing of the stranger's own account is touched or shown.
3. **A shop's customer list groups people by the phone number on the
   order.** A guest who used an account holder's number shows up as the
   same customer in that one shop. Checked: **no shop can see another
   shop's customers.**
4. **The guest's link is the guest's only key for 60 days.** Whoever holds
   it sees the order and the handover code, and can cancel before the shop
   answers. Otherwise it is well protected: it can't be guessed, it isn't
   logged and it isn't passed on to other sites.
5. **Gate photos are never deleted.** "Remove" only unlinks the photo from
   the address. An old shop logo also stays online at a hidden address.
   This needs a rule on how long such photos are kept.
6. **The guest's price-review step has no rate limit of its own.** It
   reveals nothing about anyone; the only cost is server work.
7. **The 30 days count from when the account was made,** not from its
   first sign-in (still provisional).
8. **The shop's customer list gets slower as a shop grows.** Not a safety
   problem.

### Checked and found sound

| Area | Result |
| --- | --- |
| Reaching someone else's account, orders, address, phone or shop, including guest checkout and the guest's cancel link | No way found |
| Gate photos or personal details shown to the wrong people | Gate photos are seen only by the buyer and the shop delivering that order, through a 5-minute link; never by staff |
| One shop seeing another shop's customers | Not possible |
| Getting around the buying limits or the 30-day rule | Only the guest-number point above (N1) |
| Uploads | Only real JPEG, PNG or WebP pictures; size and "picture bomb" limits; metadata and location removed; every picture redrawn |
| Backups | Gate photos and logos are included; the two new database changes only add things and can't run backwards |

---

## Part 2: C-27, the notice before ordering

**What a buyer sees:** on the last checkout step, right above **"Place
order"**, a box titled **"Before you place your order"** with four short
points. It appears for signed-in buyers and for guests, in English or
Amharic. "Place order" can't be pressed until the notice has loaded.

**It is marked PROVISIONAL.** The words live in **one file**,
`apps/api/markx/orders/notice.py`, with both languages side by side. To
change the wording, edit only that file. MarkX fills in two things itself:
the shops' legal names, and the number of hours for reporting a problem
(the real setting, 72 hours today).

### The draft, English

1. You are buying from {the shops' legal names}. Each shop sells its own
   goods and is responsible for them. MarkX connects you with the shop: it
   does not sell the goods and never holds your money.
2. You pay the shop when you receive your order, in the way you chose. Do
   not pay anyone before the goods are in front of you.
3. Check the goods before you pay: that they are what you ordered, that
   they work and that nothing is damaged. Give your handover code only
   after you have checked them. If something is wrong, do not pay and do
   not give the code.
4. *Signed-in buyer:* If there is a problem after you receive the goods,
   report it from your order page within 72 hours. MarkX staff look at it
   with the shop.
   *Guest:* As a guest you cannot report a problem on MarkX after the goods
   are handed over, so check everything at the door. Until the shop
   answers, you can cancel from your order page; once it confirms, its
   phone number is shown there.

### The draft, Amharic (please have the native editor check it)

1. የሚገዙት ከ{ሱቆቹ ሕጋዊ ስም} ነው። እያንዳንዱ ሱቅ የራሱን ዕቃ ይሸጣል፤ ለዕቃውም ኃላፊነት አለበት። ማርክኤክስ ከሱቁ ጋር ያገናኝዎታል፦ ዕቃውን አይሸጥም፤ ገንዘብዎንም ፈጽሞ አይይዝም።
2. ክፍያውን ለሱቁ የሚፈጽሙት ትዕዛዝዎን ሲቀበሉ ነው፣ በመረጡት የክፍያ መንገድ። ዕቃው በፊትዎ ሳይቀርብ ለማንም አይክፈሉ።
3. ከመክፈልዎ በፊት ዕቃውን ይፈትሹ፦ ያዘዙት መሆኑን፣ እንደሚሠራና ምንም ጉዳት እንደሌለበት። የማስረከቢያ ኮድዎን የሚሰጡት ከፈተሹ በኋላ ብቻ ነው። ችግር ካለ አይክፈሉ፤ ኮዱንም አይስጡ።
4. *የተመዘገበ ገዢ:* ዕቃውን ከተቀበሉ በኋላ ችግር ካጋጠመዎ፣ በ72 ሰዓት ውስጥ ከትዕዛዝ ገጽዎ ያሳውቁ። የማርክኤክስ ሠራተኞች ከሱቁ ጋር ሆነው ይመለከቱታል።
   *እንግዳ:* እንደ እንግዳ ስላዘዙ ዕቃውን ከተረከቡ በኋላ በማርክኤክስ ላይ ችግር ማሳወቅ አይችሉም፤ ስለዚህ ሁሉንም በር ላይ ይፈትሹ። ሱቁ መልስ እስኪሰጥ ድረስ ከትዕዛዝ ገጽዎ መሰረዝ ይችላሉ፤ ሱቁ ካረጋገጠ በኋላ ስልክ ቁጥሩ እዚያው ይታያል።

**Why the guest's last point is different:** guests really have no way to
report a problem on MarkX after the handover. The notice says so honestly
instead of promising something that doesn't exist.

### Tests

- **9 new tests on the server side and 2 on the web side.** The two
  browser journeys (signed-in buyer and guest) now also check that the
  notice is there before "Place order".
- **On the old code the new tests fail:**
  - The server test file can't load at all.
  - With only the new words file copied in, all 7 tests of the review step
    fail, because the notice isn't there.
  - The web test can't load.
- **On the new code they pass.**
- **No existing test or check was changed or weakened.**

### The pull request and its checks

- **Pull request #18:**
  https://github.com/shumetmamo21-cyber/markx-marketplace/pull/18
- **Last commit:** `dafbdd9`.
- **Every check passed on `dafbdd9`, 8 of 8:**
  - **CI run #195:** the server (lint, types, database changes, the whole
    test suite), the web app, containers, security scan, and the rehearsal
    of the production setup.
  - **Browser journeys run #71.**
  - The exact number of server tests in run #195 is UNKNOWN: the part of
    the log I read doesn't show it. The job itself passed.
- **Merged** as you approved: a normal merge (not a squash), pinned to
  `dafbdd9`, with the branch kept.
- **New main commit:** `9ce3c8d` (`9ce3c8dff96332d455109fd9d0d74651c7510b20`).
- **Main's checks on `9ce3c8d`:** see "Main after the merge" below.

### Main's recent merge commits

| Merge commit | Pull request |
| --- | --- |
| `9ce3c8d` | #18, this work (D-110) |
| `b6f0429` | #17 (D-109) |
| `e06bd83` | #16 (D-108) |
| `5794234` | #15 (D-107) |
| `e1849be` | #14 (D-106) |
| `6378764` | #13 (D-105) |

### Main after the merge

Running when this file was first committed: CI #196 and Browser journeys #72 on `9ce3c8d`. Their result is added below once they finish.

---

## What needs you

1. **When to fix R17-1** (one line in the nginx settings).
2. **Your own wording for the notice (F-30),** plus:
   - the native editor's check of the Amharic;
   - whether MarkX will have a support contact a guest can use after
     delivery (today there is none; UNKNOWN);
   - whether each order should record which version of the notice the
     buyer saw (a small database change).
3. **A rule for how long gate photos are kept** (note N5).

The documents for the next session are updated:
`docs/DEVELOPMENT_STATUS.md`, `docs/DECISIONS.md` (D-110 and F-30) and
`docs/HANDOFF.md`.
