# Connecting people's Telegram accounts (D-093) and signing in with Telegram (D-101)

**Status: built and tested locally and in CI against stand-ins only. No bot
exists, no webhook is registered, nothing has ever been sent to or received
from Telegram, and the feature is OFF everywhere.** Switching it on is the
founder's decision (N-1). Seller notifications remain a launch blocker until
a real channel delivers a real order alert.

This runbook is for the future, authorised task that connects the real bot.
Do none of it without the founder's written approval.

## What it does

A signed-in person connects **their own** Telegram account to **their own**
MarkX account, so the notification system (D-092) can reach them there.
MarkX never believes a Telegram username, number or id typed into the
browser: the person proves they control the Telegram account by opening a
one-time link inside Telegram.

This flow, connecting Telegram from the account page, signs nobody in.
Since D-101 (decision SI-1) people *sign in* with the same bot through a
separate flow (below, "Signing in with Telegram"); disconnecting Telegram
here means the next Telegram sign-in with the same Telegram account
connects it again. Disconnecting only stops messages: the account still
belongs to its Telegram account (`users.bound_telegram_id`, D-101 section
2a), so no other Telegram account can sign in to it or be connected to it.

## The protocol

```text
Browser (signed in)              MarkX API                          Telegram
-------------------              ---------                          --------
POST /api/v1/me/telegram/link -> checks: linking on, customer session,
                                 10 links/hour/account
                                 locks the user row; refuses if already
                                 connected (409 telegram_already_connected)
                                 revokes any pending link of this account
                                 token = 32 random bytes, base64url (43 chars)
                                 stores HMAC-SHA256(secret key, token) only,
                                 with user, session, expiry (10 min default)
                              <- 201 {state: pending, expires_at,
                                      link: https://t.me/<bot>?start=<token>}
Person opens the link ---------------------------------------------> /start <token>
                                 POST /api/v1/telegram/webhook   <- Telegram
                                 1. secret header checked (constant time),
                                    else 401 (30 refusals/hour/address, then 429)
                                 2. body <= 64 KiB, JSON, positive update_id,
                                    else 400 (413 if larger)
                                 3. update_id inserted once; a repeat is
                                    answered {"ok": true} and does nothing
                                 4. only `message`, chat type private, sender
                                    not a bot, chat id == sender id, text
                                    exactly "/start[@bot] <payload>";
                                    anything else: {"ok": true}, nothing changes
                                 5. 20 attempts/hour per Telegram account
                                 6. owner found by the token's hash; the user's
                                    row locked, then the token row:
                                    unknown/used/revoked -> "not valid"
                                    expired -> "not valid or has expired"
                                 7. account still active, the session that
                                    asked not signed out or expired
                                 8. advisory lock on this Telegram account;
                                    already linked elsewhere -> refused
                                    (same words whatever the reason);
                                    users.telegram_id is unique (backstop)
                                 9. link; token consumed (or failed); audit
                              -> 200 {"method": "sendMessage", "chat_id": ...,
                                      "text": <bilingual confirmation>}
Browser polls GET /api/v1/me/telegram every 3 s while waiting -> connected
```

The bot's reply travels **in the webhook's HTTP response** (Telegram's
documented "reply to a webhook" form), so the API makes no outbound call to
Telegram for linking. Confirm this form is still supported when the bot is
connected; if it is not, the reply can be dropped without affecting linking.

Every token is used at most once: any completion, successful or refused,
ends it. Asking for a new link, cancelling, disconnecting or linking by the
Mini App revokes the pending one.

## Routes

| Route | Who | What |
| --- | --- | --- |
| `GET /api/v1/me/telegram` | signed in | `{available, telegram_messages_on, state, connected_at, expires_at, link: null}`; state is `not_connected`, `pending`, `connected`, `expired`, `failed` or `disconnected`. Never the Telegram id or name |
| `POST /api/v1/me/telegram/link` | signed in, customer session | a new one-time link (201); 503 `telegram_linking_unavailable` when off; 409 when already connected; 429 after 10 an hour |
| `DELETE /api/v1/me/telegram` | signed in | disconnect and cancel any waiting link. **Always allowed, even when linking is off** |
| `POST /api/v1/telegram/webhook` | Telegram, by secret header | 404 when off; see the protocol |
| `POST /api/v1/me/telegram` | signed in | the existing Mini App link (Telegram-signed start-up data); now also OFF unless linking is on, and its refusal no longer says whether the Telegram account belongs to someone else |

Every route acts on the caller's own account only. No route takes another
person's id, and no store screen shows anyone's Telegram.

## Settings

| Variable | Default | Meaning |
| --- | --- | --- |
| `MARKX_TELEGRAM_LINKING_ENABLED` | `false` | The switch for the link, the webhook and the Mini App link |
| `MARKX_TELEGRAM_BOT_USERNAME` | unset | The bot's username without `@` (5 to 32 characters ending in `bot`). Required when on. Not a secret |
| `MARKX_TELEGRAM_WEBHOOK_SECRET` | unset | 32 to 256 of `A-Z a-z 0-9 _ -`. Required when on. Staging and production refuse values containing `dev-only`, `test-only` or `change-me`. A secret: host secret store only |
| `MARKX_TELEGRAM_LINK_TTL_MINUTES` | `10` | How long a link works (2 to 30) |

Related, unchanged (D-092): `MARKX_TELEGRAM_BOT_TOKEN`,
`MARKX_TELEGRAM_PUSH_PROVIDER` (`none` on a real server unless set to
`bot_api`). **Linking does not send anything.** Messages reach Telegram only
while the push provider is `bot_api`. With linking on and no provider, the
API logs a start-up warning and the account page says "MarkX does not send
messages to Telegram yet".

The API refuses to start when linking is on without the username or the
secret, and names the missing setting without printing any value.

## Switching it on (a future, authorised task)

1. The founder decides N-1 and approves creating the bot.
2. The founder creates the bot with @BotFather and keeps the token in the
   host's secret store. Never in chat, a file in Git, or a screenshot.
3. Make the webhook secret on the server:
   `python -c "import secrets; print(secrets.token_urlsafe(48))"`, into the
   secret store.
4. Set on the API: `MARKX_TELEGRAM_BOT_TOKEN`,
   `MARKX_TELEGRAM_BOT_USERNAME`, `MARKX_TELEGRAM_WEBHOOK_SECRET`,
   `MARKX_TELEGRAM_LINKING_ENABLED=true`, and (to send messages)
   `MARKX_TELEGRAM_PUSH_PROVIDER=bot_api`. Restart; check the start-up log
   for refusals or warnings.
5. Register the webhook with Telegram's `setWebhook`, using the site's
   public HTTPS address `https://<domain>/api/v1/telegram/webhook`, the same
   `secret_token`, and `allowed_updates=["message"]`. Re-read Telegram's Bot
   API documentation first: this was written without reaching it.
6. Check `getWebhookInfo`: no `last_error_message`, `pending_update_count`
   falling to 0.
7. Connect the founder's own Telegram from the account page; confirm the
   page turns "Connected" and the bot answers. Then place a test order to a
   store the founder owns and confirm the alert arrives and its delivery
   record says `accepted`.
8. **Signing in with Telegram (D-101) comes on with the same switch.**
   Before switching on, re-read the Bot API documentation for the
   `contact` message (its `user_id` must be the sender's own id for a
   number shared with the `request_contact` button) and for a webhook reply
   carrying `reply_markup` (the keyboard with the share button, then
   `remove_keyboard`); both were written without reaching the
   documentation. Then sign the founder in on a phone: "Sign in with
   Telegram", Open Telegram, Start, "Share my phone number", back to the
   page, which signs in by itself; the founder's MarkX number must be the
   one Telegram holds. Then the staff page: Telegram, then the password and
   authenticator code.
9. Record the result in `docs/DEVELOPMENT_STATUS.md` with the date.

To switch it off again: set `MARKX_TELEGRAM_LINKING_ENABLED=false` and
restart (the webhook answers 404; Telegram will report errors until
`deleteWebhook` is called). Existing connections stay and can still be
disconnected; to stop all Telegram messages, set the push provider to
`none`.

## Signing in with Telegram (D-101, decision SI-1)

Everyone signs in on the website with this bot. The browser asks
`POST /api/v1/auth/telegram/sign-in` and gets a one-time link
`https://t.me/<bot>?start=si-<token>` plus a private secret in an HttpOnly
cookie (`markx_tg_sign_in`, path `/api/v1/auth/telegram/sign-in`). The bot,
on `/start si-<token>`, answers with a keyboard of one button that asks
Telegram for the person's own number (`request_contact`). The contact that
comes back is accepted only if its `user_id` is the sender's id and it was
not forwarded, and only for an Ethiopian mobile number. The browser asks
`POST /api/v1/auth/telegram/sign-in/check` until it is signed in (once).
Which account a number and a Telegram account reach, and what happens when
either changed, is the table in D-101 (PROVISIONAL P-101-6). Staff then add
their password and code at `POST /api/v1/auth/staff/step-up`. Off whenever
linking is off: `POST /auth/telegram/sign-in` answers 503
`telegram_sign_in_unavailable` and the page offers no Telegram button.

## How the webhook is verified

Telegram repeats the `secret_token` given to `setWebhook` in the
`X-Telegram-Bot-Api-Secret-Token` header of every call. The API compares it
in constant time **before reading the body**, refuses a missing or wrong one
with 401 and logs only that it refused (never the value), and counts refusals
per address (429 after 30 an hour). The path is the only exemption from the
browser anti-forgery guard (`CSRF_EXEMPT_PATHS`, exact match). Rotating the
secret: set a new `MARKX_TELEGRAM_WEBHOOK_SECRET`, restart, then call
`setWebhook` again with it; calls in between are refused and Telegram
retries them.

Optional hardening for that task: restrict the path at nginx to Telegram's
published address ranges.

## Disconnecting

- **The person**: Account → Telegram messages → Disconnect Telegram → Yes,
  disconnect. Or `DELETE /api/v1/me/telegram`.
- **What happens**: `users.telegram_id` and `telegram_linked_at` are
  cleared, `telegram_unlinked_at` is set, waiting links are revoked, the
  audit log records `telegram.unlinked`. Every later notification records the
  Telegram delivery `skipped` / `no_telegram_linked` (the delivery reads the
  link at each attempt). `users.bound_telegram_id` is **kept** (a database
  trigger refuses to clear or change it): only that Telegram account may
  sign in to the account or be connected to it again, so a stranger given
  the same recycled number cannot take the account over (P-101-6).
- **Staff** have no screen to disconnect someone. If a person has lost their
  Telegram account, disconnecting does not let them use a new one: they
  must contact support, and no support tool exists yet (F-24).

## What is recorded

- `telegram_link_tokens`: keyed hash, user, session, times, status, failure
  reason. Never the token. Deleted 30 days after creation by
  `retention.prune`.
- `telegram_updates`: update id and time only. Deleted after 7 days.
- `audit_log`: `telegram.link_requested`, `telegram.linked` (with
  `method`: `bot_link` or `mini_app`), `telegram.link_refused` (with the
  reason), `telegram.unlinked`. Never a token, Telegram id or name.
- Logs: outcomes only (`linked`, `invalid`, `expired`, `refused`, why an
  update was ignored). Never a token, Telegram id, message text or secret.

## Limitations

- Never tested against Telegram. The webhook's request and reply shapes
  follow Telegram's Bot API as known when written.
- Notifications that were `skipped` or `unavailable` before a person
  connected are **not** resent. A manual resend is a separate future task.
- A notification already being sent at the moment of disconnecting may
  still go out once.
- No staff screen for connections; no Telegram sign-in on the web.
- The bot's replies are fixed bilingual texts in the API
  (`markx/accounts/telegram_link.py`) and need a native speaker's review.
