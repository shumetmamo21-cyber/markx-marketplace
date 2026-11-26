"""The notice a buyer reads before placing an order (blueprint D.10, C-27; D-110).

**PROVISIONAL (P-110-1), to be replaced by the founder's own wording before
going live.** The founder has not written this notice yet. The words below
are a plain draft by an engineering session: who sells, paying at the door,
checking the goods before paying, and how to raise a problem. The Amharic
needs the native editor's check.

**This file is the one place the notice lives.** To change the wording,
edit `TEXT` below and nothing else: the review step of the signed-in
checkout and of the guest checkout both show exactly these words, in the
buyer's language, right above the "Place order" button. Keep the two
placeholders where they make sense:

- `{sellers}`: the legal names of the shops in this order, filled in by the
  server from the review step's own figures;
- `{hours}`: how long after delivery a signed-in buyer may report a problem
  (the setting `orders.problem_window_hours`), so the notice never promises
  a different time than the order page allows.

When the wording changes, change `VERSION` too, so it is clear which words a
buyer was shown.

The notice is not a business rule and changes no limit, price or check: it
tells the buyer the rules that already apply.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from markx.core import settings_store

VERSION = "c27-draft-2026-11-26"
PROVISIONAL = True

TEXT: dict[str, dict[str, str]] = {
    "en": {
        "title": "Before you place your order",
        "who_sells": (
            "You are buying from {sellers}. Each shop sells its own goods and is responsible "
            "for them. MarkX connects you with the shop: it does not sell the goods and never "
            "holds your money."
        ),
        "pay_at_door": (
            "You pay the shop when you receive your order, in the way you chose. Do not pay "
            "anyone before the goods are in front of you."
        ),
        "check_goods": (
            "Check the goods before you pay: that they are what you ordered, that they work and "
            "that nothing is damaged. Give your handover code only after you have checked them. "
            "If something is wrong, do not pay and do not give the code."
        ),
        "problem_account": (
            "If there is a problem after you receive the goods, report it from your order page "
            "within {hours} hours. MarkX staff look at it with the shop."
        ),
        "problem_guest": (
            "As a guest you cannot report a problem on MarkX after the goods are handed over, "
            "so check everything at the door. Until the shop answers, you can cancel from your "
            "order page; once it confirms, its phone number is shown there."
        ),
    },
    "am": {
        "title": "ትዕዛዝዎን ከማስገባትዎ በፊት",
        "who_sells": (
            "የሚገዙት ከ{sellers} ነው። እያንዳንዱ ሱቅ የራሱን ዕቃ ይሸጣል፤ ለዕቃውም ኃላፊነት አለበት። "
            "ማርክኤክስ ከሱቁ ጋር ያገናኝዎታል፦ ዕቃውን አይሸጥም፤ ገንዘብዎንም ፈጽሞ አይይዝም።"
        ),
        "pay_at_door": (
            "ክፍያውን ለሱቁ የሚፈጽሙት ትዕዛዝዎን ሲቀበሉ ነው፣ በመረጡት የክፍያ መንገድ። ዕቃው በፊትዎ ሳይቀርብ ለማንም አይክፈሉ።"
        ),
        "check_goods": (
            "ከመክፈልዎ በፊት ዕቃውን ይፈትሹ፦ ያዘዙት መሆኑን፣ እንደሚሠራና ምንም ጉዳት እንደሌለበት። "
            "የማስረከቢያ ኮድዎን የሚሰጡት ከፈተሹ በኋላ ብቻ ነው። ችግር ካለ አይክፈሉ፤ ኮዱንም አይስጡ።"
        ),
        "problem_account": (
            "ዕቃውን ከተቀበሉ በኋላ ችግር ካጋጠመዎ፣ በ{hours} ሰዓት ውስጥ ከትዕዛዝ ገጽዎ ያሳውቁ። "
            "የማርክኤክስ ሠራተኞች ከሱቁ ጋር ሆነው ይመለከቱታል።"
        ),
        "problem_guest": (
            "እንደ እንግዳ ስላዘዙ ዕቃውን ከተረከቡ በኋላ በማርክኤክስ ላይ ችግር ማሳወቅ አይችሉም፤ "
            "ስለዚህ ሁሉንም በር ላይ ይፈትሹ። ሱቁ መልስ እስኪሰጥ ድረስ ከትዕዛዝ ገጽዎ መሰረዝ ይችላሉ፤ "
            "ሱቁ ካረጋገጠ በኋላ ስልክ ቁጥሩ እዚያው ይታያል።"
        ),
    },
}

_PLACEHOLDER = re.compile(r"\{(sellers|hours)\}")

# The order the points are shown in; the last one depends on who is buying.
_POINTS = ("who_sells", "pay_at_door", "check_goods")


def _names(language: str, names: list[str]) -> str:
    """The names joined as "A", "A and B" or "A, B and C", in the buyer's language."""
    joiner, last = ("፣ ", " እና ") if language == "am" else (", ", " and ")
    if len(names) <= 1:
        return "".join(names)
    return joiner.join(names[:-1]) + last + names[-1]


def order_notice(
    db: Session, seller_legal_names: list[str], language: str, *, guest: bool
) -> dict[str, Any]:
    """The notice for one review step: the title and its four points, in the
    buyer's language, with the shops' legal names and the problem window
    filled in. `guest` picks how a problem is raised: a guest has no order
    page to report one on (C-07, D-108)."""
    words = TEXT[language]
    names = list(dict.fromkeys(name for name in seller_legal_names if name))
    hours = str(settings_store.get_int(db, "orders.problem_window_hours"))
    keys = (*_POINTS, "problem_guest" if guest else "problem_account")
    values = {"sellers": _names(language, names), "hours": hours}
    # One pass, never `str.format`: a shop's legal name may hold braces, and
    # what is filled in is never read again as a placeholder.
    points = [_PLACEHOLDER.sub(lambda m: values[m.group(1)], words[key]) for key in keys]
    return {
        "version": VERSION,
        "provisional": PROVISIONAL,
        "title": words["title"],
        "points": points,
    }
