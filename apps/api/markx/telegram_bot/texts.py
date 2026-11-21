"""The bot's own words (D-102), in English and Amharic.

Every reply is in the person's language (Amharic unless they chose English).
A reply names only what the person may already see in MarkX: an order's code,
its state, how many items it has, the names of the products ordered (F-26,
decided by the founder; D-104) and how long is left to answer; for offers,
the store's own public listing (product, price, stock). Never a buyer's name,
phone number, address or handover code, and never an order's prices.

`{…}` fields are filled by `say` with values the bot made itself (codes,
counts, minutes, offer references) or with the store's own product names,
made into one short line of plain text by `telegram_bot.products`; never
with text a buyer typed.
"""

from __future__ import annotations

from typing import Any

TEXTS: dict[str, dict[str, str]] = {
    # -- general ---------------------------------------------------------------------
    "help": {
        "en": "MarkX seller bot. Commands:\n"
        "/orders – orders waiting for you, with Accept, Decline, Ready and Sent buttons\n"
        "/offers – your listings and their references\n"
        "/price REF AMOUNT – a new price in birr, for example /price 4F2A9C 12500\n"
        "/stock REF COUNT – how many you have, for example /stock 4F2A9C 3\n"
        "/checkin – all your prices and stock are still right\n"
        "/help – this list",
        "am": "የMarkX የሻጭ ቦት። ትዕዛዞች፦\n"
        "/orders – እርስዎን የሚጠብቁ ትዕዛዞች፣ በ«ተቀበል»፣ «አትቀበል»፣ «ዝግጁ» እና «ተልኳል» ቁልፎች\n"
        "/offers – ምርቶችዎና መለያ ቁጥሮቻቸው\n"
        "/price መለያ ዋጋ – አዲስ ዋጋ በብር፣ ለምሳሌ /price 4F2A9C 12500\n"
        "/stock መለያ ብዛት – ያለዎት ብዛት፣ ለምሳሌ /stock 4F2A9C 3\n"
        "/checkin – ዋጋዎችዎና ብዛቶችዎ ሁሉ አሁንም ትክክል ናቸው\n"
        "/help – ይህ ዝርዝር",
    },
    "not_a_seller": {
        "en": "Your MarkX account does not handle a store's orders or listings, so there is "
        "nothing for you here yet.",
        "am": "የMarkX መለያዎ የሱቅ ትዕዛዞችን ወይም ምርቶችን አያስተዳድርም፤ ስለዚህ እዚህ ለእርስዎ ገና ምንም የለም።",
    },
    "failed": {
        "en": "MarkX could not do that. Open MarkX to see why.",
        "am": "MarkX ይህን ማድረግ አልቻለም። ምክንያቱን በMarkX ይመልከቱ።",
    },
    # -- the order inbox (S-07) --------------------------------------------------------
    "inbox_title": {
        "en": "Orders waiting for you:",
        "am": "እርስዎን የሚጠብቁ ትዕዛዞች፦",
    },
    "inbox_empty": {
        "en": "No order is waiting for you. New orders arrive here with Accept and Decline "
        "buttons.",
        "am": "እርስዎን የሚጠብቅ ትዕዛዝ የለም። አዲስ ትዕዛዞች በ«ተቀበል» እና «አትቀበል» ቁልፎች እዚህ ይደርሳሉ።",
    },
    "inbox_more": {
        "en": "…and {more} more. Open MarkX to see them all.",
        "am": "…እና ሌሎች {more}። ሁሉንም በMarkX ይመልከቱ።",
    },
    "order_line": {
        "en": "{code}: {state}, {items} item(s)",
        "am": "{code}፦ {state}፣ {items} ዕቃ",
    },
    # The products ordered (F-26, D-104), on the line under the order.
    "order_products": {
        "en": "   Products: {products}",
        "am": "   ምርቶች፦ {products}",
    },
    "products_more": {
        "en": "{names} and {more} more",
        "am": "{names} እና ሌሎች {more}",
    },
    "minutes_left": {
        "en": "{minutes} min left to answer",
        "am": "ለመመለስ {minutes} ደቂቃ ቀርቷል",
    },
    "choose_reason": {
        "en": "Why can you not fill order {code}? The buyer is told and shown other offers.",
        "am": "ትዕዛዝ {code}ን ለምን ማሟላት አይችሉም? ገዢው ይነገራቸዋል፤ ሌሎች ቅናሾችም ይታያቸዋል።",
    },
    "done_accepted": {"en": "✅ You accepted order {code}.", "am": "✅ ትዕዛዝ {code}ን ተቀብለዋል።"},
    "done_declined": {"en": "You declined order {code}.", "am": "ትዕዛዝ {code}ን አልተቀበሉም።"},
    "done_ready": {
        "en": "✅ Order {code} is marked packed and ready.",
        "am": "✅ ትዕዛዝ {code} ታሽጎ ዝግጁ መሆኑ ተመዝግቧል።",
    },
    "done_sent": {
        "en": "✅ Order {code} is marked on its way.",
        "am": "✅ ትዕዛዝ {code} መላኩ ተመዝግቧል።",
    },
    "handover_on_web": {
        "en": "Enter the buyer's handover code in MarkX when you hand the order over. "
        "Never type it here.",
        "am": "ትዕዛዙን ሲያስረክቡ የገዢውን የማስረከቢያ ኮድ በMarkX ያስገቡ። እዚህ በፍጹም አይጻፉት።",
    },
    # -- buttons -----------------------------------------------------------------------
    "btn_accept": {"en": "✅ Accept", "am": "✅ ተቀበል"},
    "btn_decline": {"en": "✖ Decline", "am": "✖ አትቀበል"},
    "btn_ready": {"en": "📦 Packed and ready", "am": "📦 ታሽጓል፣ ዝግጁ ነው"},
    "btn_sent": {"en": "🛵 On its way", "am": "🛵 ተልኳል"},
    "btn_inbox": {"en": "📥 Orders waiting", "am": "📥 የሚጠብቁ ትዕዛዞች"},
    "btn_open": {"en": "Open in MarkX", "am": "በMarkX ክፈት"},
    "btn_back": {"en": "‹ Back", "am": "‹ ተመለስ"},
    "btn_checkin": {"en": "✔ All still right", "am": "✔ ሁሉም አሁንም ትክክል ነው"},
    # The decline reasons a button can give (PROVISIONAL P-102-2). Stored on the
    # order in the seller's language, as a reason typed on the website is.
    "reason_0": {"en": "Out of stock", "am": "ዕቃው አልቋል"},
    "reason_1": {"en": "The price has changed", "am": "ዋጋው ተቀይሯል"},
    "reason_2": {
        "en": "Cannot deliver to this area in time",
        "am": "ወደዚህ አካባቢ በጊዜው ማድረስ አይቻልም",
    },
    # -- order states, as the seller reads them ----------------------------------------
    "state_placed": {"en": "waiting for your answer", "am": "መልስዎን እየጠበቀ"},
    "state_confirmed": {"en": "accepted, to pack", "am": "ተቀብለዋል፣ መታሸግ አለበት"},
    "state_paid": {"en": "paid, to pack", "am": "ተከፍሏል፣ መታሸግ አለበት"},
    "state_ready": {"en": "packed, to send", "am": "ታሽጓል፣ መላክ አለበት"},
    "state_ready_collection": {
        "en": "packed, waiting for the buyer to collect",
        "am": "ታሽጓል፣ ገዢው እስኪወስድ እየጠበቀ",
    },
    "state_out_for_delivery": {"en": "on its way", "am": "በመንገድ ላይ"},
    "state_delivery_failed": {
        "en": "delivery failed, to send again",
        "am": "ማድረስ አልተሳካም፣ እንደገና መላክ",
    },
    "state_delivered": {"en": "delivered", "am": "ደርሷል"},
    "state_completed": {"en": "completed", "am": "ተጠናቋል"},
    "state_declined": {"en": "declined", "am": "አልተቀበሉትም"},
    "state_expired": {"en": "expired, not answered in time", "am": "በጊዜው ስላልተመለሰ ጊዜው አልፏል"},
    "state_cancelled": {"en": "cancelled", "am": "ተሰርዟል"},
    "state_returned": {"en": "returned to the shop", "am": "ወደ ሱቁ ተመልሷል"},
    "state_disputed": {"en": "problem reported", "am": "ችግር ተነግሯል"},
    "state_refunded": {"en": "refunded", "am": "ገንዘቡ ተመልሷል"},
    # -- listings (S-24) ---------------------------------------------------------------
    "offers_title": {
        "en": "Your listings (REF, product, price, stock):",
        "am": "ምርቶችዎ (መለያ፣ ምርት፣ ዋጋ፣ ብዛት)፦",
    },
    "offers_empty": {"en": "You have no listings yet.", "am": "እስካሁን ምንም ምርት የለዎትም።"},
    "offer_line": {
        "en": "{ref} {name}: ETB {price}, {available} available{flag}",
        "am": "{ref} {name}፦ {price} ብር፣ {available} አለ{flag}",
    },
    "flag_stale": {"en": " (price to confirm)", "am": " (ዋጋው መረጋገጥ አለበት)"},
    "flag_paused": {"en": " (paused)", "am": " (ቆሟል)"},
    "price_set": {
        "en": "✅ {ref}: the price is now ETB {price}.",
        "am": "✅ {ref}፦ ዋጋው አሁን {price} ብር ነው።",
    },
    "stock_set": {
        "en": "✅ {ref}: {on_hand} in stock, {available} available to buyers.",
        "am": "✅ {ref}፦ {on_hand} በክምችት፣ ለገዢዎች {available} አለ።",
    },
    "checked_in": {
        "en": "✅ Thank you: {count} listing(s) confirmed as still right today.",
        "am": "✅ እናመሰግናለን፦ {count} ምርት(ዎች) ዛሬም ትክክል መሆናቸው ተረጋግጧል።",
    },
    "usage_price": {
        "en": "Send it like this: /price 4F2A9C 12500 (the REF from /offers, then birr).",
        "am": "እንዲህ ይላኩ፦ /price 4F2A9C 12500 (ከ/offers ያገኙት መለያ፣ ከዚያ ብር)።",
    },
    "usage_stock": {
        "en": "Send it like this: /stock 4F2A9C 3 (the REF from /offers, then the count).",
        "am": "እንዲህ ይላኩ፦ /stock 4F2A9C 3 (ከ/offers ያገኙት መለያ፣ ከዚያ ብዛቱ)።",
    },
    "offer_unknown": {
        "en": "No listing of yours has that REF. Send /offers to see them.",
        "am": "ያ መለያ ያለው ምርት የለዎትም። ለማየት /offers ይላኩ።",
    },
    # -- why something was refused (the same rules as the website) --------------------
    "err_order_not_found": {"en": "That order was not found.", "am": "ያ ትዕዛዝ አልተገኘም።"},
    "err_permission_denied": {
        "en": "Your role in this store does not allow this.",
        "am": "በዚህ ሱቅ ያለዎት ሚና ይህን አይፈቅድም።",
    },
    "err_seller_closed": {"en": "This store is closed.", "am": "ይህ ሱቅ ተዘግቷል።"},
    "err_seller_not_active": {
        "en": "Your store must be approved and active to do this.",
        "am": "ይህን ለማድረግ ሱቅዎ የጸደቀና ንቁ መሆን አለበት።",
    },
    "err_order_not_awaiting_response": {
        "en": "Order {code} is no longer waiting for your answer.",
        "am": "ትዕዛዝ {code} ከእንግዲህ መልስዎን አይጠብቅም።",
    },
    "err_response_window_closed": {
        "en": "The time to answer order {code} has passed.",
        "am": "ትዕዛዝ {code}ን ለመመለስ የነበረው ጊዜ አልፏል።",
    },
    "err_order_move_not_allowed": {
        "en": "Order {code} cannot do that now.",
        "am": "ትዕዛዝ {code} አሁን ይህን ማድረግ አይችልም።",
    },
    "err_collection_order": {
        "en": "The buyer collects order {code} at the shop: enter their handover code in MarkX.",
        "am": "ገዢው ትዕዛዝ {code}ን ከሱቁ ይወስዳሉ፤ የማስረከቢያ ኮዳቸውን በMarkX ያስገቡ።",
    },
    "err_price_invalid": {"en": "Enter a price above zero.", "am": "ከዜሮ በላይ ዋጋ ያስገቡ።"},
    "err_stock_invalid": {
        "en": "Enter a stock count from 0 upward.",
        "am": "ከ0 ጀምሮ ያለ ብዛት ያስገቡ።",
    },
    "err_stock_below_reserved": {
        "en": "Some units are held for open orders; stock cannot go below that.",
        "am": "አንዳንድ ዕቃዎች ለክፍት ትዕዛዞች ተይዘዋል፤ ብዛቱ ከዚያ በታች ሊሆን አይችልም።",
    },
    "err_offer_removed": {
        "en": "That listing was removed. Create it again in MarkX to relist.",
        "am": "ያ ምርት ተወግዷል። እንደገና ለመዘርዘር በMarkX ይፍጠሩት።",
    },
    "err_offer_not_found": {"en": "That listing was not found.", "am": "ያ ምርት አልተገኘም።"},
}

# The reason codes the website's services raise that the bot explains in its
# own words; anything else is "failed" (open MarkX to see why).
ERROR_TEXTS = frozenset(key[4:] for key in TEXTS if key.startswith("err_"))
# NotFound for a store answers like a missing order: never "not your store".
ERROR_ALIASES = {"seller_not_found": "order_not_found"}
DECLINE_REASONS = ("reason_0", "reason_1", "reason_2")


def lang_of(language: str | None) -> str:
    return "en" if language == "en" else "am"


def say(key: str, language: str | None, **values: Any) -> str:
    """One text in one language, with the bot's own values filled in."""
    words = TEXTS[key][lang_of(language)]
    return words.format(**values) if values else words


def error_text(code: str, language: str | None, order_code: str | None = None) -> str:
    code = ERROR_ALIASES.get(code, code)
    if code not in ERROR_TEXTS:
        return say("failed", language)
    return say(f"err_{code}", language, code=order_code or "")
