"""The settings' descriptions in Amharic, for the admin settings screen
(blueprint I.1: two languages, equal quality; D-078).

One entry per setting in `settings_store.SETTINGS`; a unit test fails when a
setting has none. Drafted by an AI agent: a native speaker must review them
before launch (blueprint I.3), as for every Amharic text in MarkX.
"""

from __future__ import annotations

DESCRIPTIONS_AM: dict[str, str] = {
    "sellers.invite_only": "ማመልከት የሚችሉት የተጋበዙ ሻጮች ብቻ ናቸው (ብሉፕሪንት D.3)።",
    "sellers.individual_enabled": "ግለሰብ ሻጮች ማመልከት ይችላሉ። የመሥራቹ የሕግ ማረጋገጫ እስኪደረግ ድረስ ጠፍቷል (ክፍል O፣ ጥያቄ 10)።",
    "sellers.min_level_to_publish": "የሻጭ ቅናሾች ከመታየታቸው በፊት የሚያስፈልገው የማረጋገጫ ደረጃ።",
    "sellers.invitation_valid_days": "ለማመልከት የተላከ ግብዣ ክፍት ሆኖ የሚቆይባቸው ቀናት።",
    "sellers.starter_seats": "በነፃ ዕቅድ ያለ ሻጭ ሊኖሩት የሚችሉ አባላት፣ ባለቤቱን ጨምሮ (ብሉፕሪንት D.4)።",
    "sellers.payout_cooling_off_hours": "የተቀየረ የክፍያ መቀበያ ሂሳብ ሥራ ላይ ከመዋሉ በፊት ያሉት ሰዓታት (S-13)።",
    "sellers.recheck_after_days": "የሻጭ ማረጋገጫ እንደገና የሚፈተሽባቸው ቀናት (ብሉፕሪንት D.3)።",
    "sellers.document_max_bytes": "ሻጭ ሊሰቅለው የሚችለው ትልቁ የሰነድ ፎቶ መጠን፣ በባይት።",
    "sellers.weekly_report_enabled": "ለእያንዳንዱ የሚነግድ ሱቅ ሳምንታዊ የአፈጻጸም መልዕክቱን (S-26) ከእያንዳንዱ ሳምንት በኋላ ላክ፤ ሳምንቱ ከሰኞ እስከ እሁድ በአዲስ አበባ ሰዓት ነው።",
    "offers.sink_after_days": "ዋጋው ለዚህ ያህል ቀናት ያልተረጋገጠ ቅናሽ በደረጃው ይወርዳል።",
    "offers.stale_after_days": "ዋጋው ለዚህ ያህል ቀናት ያልተረጋገጠ ቅናሽ ይደበቃል (ብሉፕሪንት D.7)።",
    "orders.response_window_minutes": "ሻጭ ትዕዛዝን ለመመለስ ያለው ጊዜ፣ በሥራ ሰዓታት (በደቂቃ)።",
    "orders.business_open_hour": "የሥራ ቀን መጀመሪያ፣ በአዲስ አበባ ሰዓት (የ24 ሰዓት አቆጣጠር)።",
    "orders.business_close_hour": "የሥራ ቀን መጨረሻ፣ በአዲስ አበባ ሰዓት (የ24 ሰዓት አቆጣጠር)።",
    "orders.fulfilment_hold_days": "የተቀበለ ትዕዛዝ እየታሸገና እየደረሰ ሳለ ክምችቱን የሚይዝባቸው ቀናት።",
    "orders.problem_window_hours": "ዕቃ ከደረሰ በኋላ ገዢ ችግር ማመልከት የሚችልበት ጊዜ፣ በሰዓት።",
    "orders.problem_decision_hours": "ሰራተኞች በተመለከተ ችግር ላይ የሚወስኑባቸው ሰዓታት (ብሉፕሪንት D.17)።",
    "orders.max_open_direct_orders": "አንድ ገዢ ሊይዛቸው የሚችላቸው ክፍት የበር ላይ ክፍያ ትዕዛዞች (ብሉፕሪንት D.10፣ AD-13)።",
    "orders.max_order_value_santim": "ተቀባይነት የሚያገኘው ትልቁ የትዕዛዝ ጠቅላላ ዋጋ፣ በሳንቲም (AD-13)።",
    "reviews.window_days": "አንድ ክፍል ከተጠናቀቀ በኋላ ገዢው ሊገመግመው የሚችልባቸው ቀናት፤ ሻጩ እስኪመልስ ድረስም ግምገማውን መቀየር ይችላል።",
    "reviews.per_buyer_per_day": "አንድ ገዢ በቀን ሊጽፋቸው የሚችላቸው ግምገማዎች (ብሉፕሪንት D.15፦ በሐሰተኛ ግምገማዎች ላይ ገደብ)።",
    "reviews.hold_after_same_seller": "ገዢ በ30 ቀናት ውስጥ ይህን ያህል ጊዜ የገመገመውን ሻጭ እንደገና ሲገመግም ግምገማው ከመታየቱ በፊት ሰራተኞችን ይጠብቃል (የንድፍ ፍተሻ፣ D.15)።",
    "images.max_upload_bytes": "ለመስቀል ተቀባይነት የሚያገኘው ትልቁ ፎቶ፣ በባይት። ስልኮች ከመላካቸው በፊት ያጨምቃሉ (S-06)፤ ስለዚህ እውነተኛ ፎቶ በጣም ያነሰ ነው።",
    "images.max_catalogue_per_product": "አንድ ምርት ሊኖሩት የሚችሉ የካታሎግ ፎቶዎች፣ የተወገዱትን ሳይጨምር።",
    "images.max_real_photos_per_seller": "አንድ ሻጭ በአንድ ምርት ላይ ሊያሳያቸው የሚችላቸው እውነተኛ ፎቶዎች፣ የተወገዱትን ሳይጨምር (D.5)።",
    "images.max_problem_photos_per_side": "ገዢው፣ በተናጠልም ሻጩ፣ በአንድ ችግር ላይ ሊጨምሯቸው የሚችሉ የማስረጃ ፎቶዎች (C-16)።",
    "search.requests_per_ip_per_minute": "አንድ የአውታረ መረብ አድራሻ በደቂቃ ሊያደርጋቸው የሚችላቸው ፍለጋዎች፤ ከዚያ በላይ ያሉት ለቀሪው ደቂቃ ተቀባይነት አያገኙም (ብሉፕሪንት H.2፣ D-059)።",
    "search.suggestions_per_ip_per_minute": "ገዢ ሲጽፍ አንድ የአውታረ መረብ አድራሻ በደቂቃ ሊጠይቃቸው የሚችላቸው የስም ጥቆማዎች (ብሉፕሪንት H.2፣ D-059)።",
    "auth.otp_per_phone_per_hour": "አንድ ስልክ ቁጥር በሰዓት ሊጠይቃቸው የሚችላቸው የመግቢያ ኮዶች።",
    "auth.otp_per_ip_per_hour": "አንድ የአውታረ መረብ አድራሻ በሰዓት ሊጠይቃቸው የሚችላቸው የመግቢያ ኮዶች።",
    "auth.sms_daily_budget": "ማርክኤክስ በቀን ሊልካቸው የሚችላቸው የኤስኤምኤስ መልዕክቶች፤ ሲያልቁ መላክ ይቆማል (ብሉፕሪንት D.2)።",
    "disputes.decision_due_hours": "ሰራተኞች በችግር ጉዳይ ላይ የሚወስኑባቸው ሰዓታት (ብሉፕሪንት D.17)።",
    "payments.protected_enabled": "በፈቃድ ባለው አቅራቢ በኩል የሚደረግ የተጠበቀ ክፍያ። ልቀት 2፤ በር C ያስፈልገዋል።",
}
