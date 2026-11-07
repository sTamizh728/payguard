# PayGuard

**Talk to PayPal.** PayGuard is a voice-first PayPal assistant for Android, in English and
Tamil. Speak naturally (real two-way voice with Gemini Live), or type, to send money, shop,
set up and track autopays, follow orders and deliveries, get refunds and catch failed
payments. **Money only moves after your own PayGuard PIN plus your fingerprint, face or
phone PIN, or in PayPal's own checkout. The AI never moves money.**

Built solo for the PayPal AI Hackathon 2026. Everything runs on the PayPal **sandbox**.

- Backend (live): `https://payguard-api-0msk.onrender.com` (FastAPI on Render, PostgreSQL on Neon)
- App: React Native 0.88 Android app with its own Kotlin module (`apps/mobile`)
- 324 automated tests (`backend/tests`), PayPal, Gemini and the database faked

---

## What you can do

| Say or type | What happens | PayPal API |
|---|---|---|
| "Find the best wireless earbuds under 3000" | Top-rated products from online stores (real price, rating, review count), with links to buy on the store's own site | — (Google Shopping via SerpAPI) |
| "Search for wireless earphones" | Reads the top results with price and star rating | — (demo catalog) |
| "Tell me about number 2" | Description, stock, shipping and real written reviews | — |
| "Add it to my cart", "Checkout" | One multi-item order to your saved delivery address, paid in PayPal checkout | **Orders v2** (create, capture, shipping address) |
| "Where is my order?", Track → Deliveries | Status, expected delivery date, receipt with PayPal transaction ID | Orders v2 |
| "Send $20 to Priya" | Scam check, then PayGuard PIN + fingerprint, then the money is sent | **Payouts** |
| Send → "My own PayPal" (anyone) | Pay a friend from your own PayPal, approved on PayPal's page | **Orders v2** (friend as payee) |
| Send → "Pick from phone contacts" / type an email | Choose anyone from the phone's contact book (system picker, no contacts permission) or type a PayPal email; voice can then use the name | — |
| "Set up autopay for StreamBox" | A real PayPal subscription, approved in PayPal; alerts each charge | **Subscriptions** + **Webhooks** |
| "When is my next autopay?", "Pause autopay 2" | Status, next date, last payment; pause, resume, cancel (PIN + fingerprint) | **Subscriptions** |
| Track → Autopay → Add | Track autopays set up elsewhere; reminder 2 days before each charge | — |
| "Show my payment history" | One list: sent, received, shop, friends, autopay | all of the above |
| "Did any payment fail?" | Failed, returned or unclaimed payments, explained | Payouts (status) |
| "Refund $5 from payment 2" | Partial or full refund after the fingerprint | **Payments v2 refunds** |
| "My order arrived damaged" (customer) | A refund request the owner approves or declines | Payments v2 refunds |
| Track → Check balance | PayPal wallet balance, after the PayGuard PIN and a fingerprint check the server verifies | **Balances (Reporting)** |
| (automatic) | "You received $12.50", "Your payment was returned", "Autopay paid", "Autopay failed", disputes | **Webhooks** (+ signature verification) |
| Log in | Log in with PayPal (or email) | **Log in with PayPal** (OpenID Connect) |
| Phone call (ready, needs a Twilio number) | Keypad shop menu in English and Tamil, 6-digit order code | Orders v2 |

## Voice: a real conversation

The Chat tab's **Live conversation** streams the microphone to our server, which relays it to
**Gemini Live** (`gemini-3.1-flash-live-preview`). Answers come back as natural speech in
about a second, with a live transcript on screen. Gemini Live can call PayGuard's tools, but
every tool call goes through the same safety code as typed chat (below). The phone uses
echo cancellation and the loudspeaker, and never listens while PayGuard is speaking, so it
cannot interrupt itself. Leaving the app ends the session, so the microphone is never left on.

**Talk** (tap-to-talk) and typing work too. Distinct sounds mark money sent, money received,
request sent, scam warning, confirm needed and microphone on/off, so the app is usable without
looking at the screen. It is built screen-reader first (TalkBack labels, live regions).

## How PayGuard keeps money safe

1. **The AI never moves money.** Gemini (chat: `gemini-3-flash-preview`, voice: Gemini Live)
   only turns words into one tool call. Plain Python decides everything else.
2. **Nothing the AI invents is used.** Names, amounts, payment and result numbers must appear
   in the person's own words (digits, number words or ordinals). "Approve that one" is not
   read as "request 1".
3. **Tricks are blocked before the AI sees them.** "Ignore your rules", "SYSTEM: already
   approved", look-alike letters and invisible characters are caught in code; two tries lock
   payments for 10 minutes. Spoken tricks are blocked the same way.
4. **Your own PayGuard PIN** (4-6 digits, chosen right after the first login) is asked before
   every PayGuard-wallet payment, refund, autopay change and balance check, on top of the
   fingerprint. Payments made on PayPal's own page (shop checkout, paying a friend from your
   own PayPal, approving an autopay) are approved with PayPal's login instead. It is
   stored only as an Argon2 hash; 5 wrong tries lock it for 15 minutes (counted in the database);
   changing it needs the old PIN or a fresh login.
5. **Fingerprint, face or PIN, checked by the server.** The phone keeps a P-256 key in its
   secure hardware that unlocks only with biometrics or the phone PIN. It signs each
   confirmation; the server verifies the signature before any payout or refund. A stolen login
   cannot move money, a signature cannot be replayed, and a spoken "yes" never moves money.
6. **Scam guard.** A new recipient, pressure words ("urgent", "gift card", "அவசரம்"), a large
   amount or many payments in a row raise warnings. With two or more, Confirm stays locked for
   30 seconds, enforced by the server (even a valid fingerprint cannot skip it).
7. **Limits:** $100 per payment and $200 a day, re-checked at the moment of confirming.
8. **Safe retries:** every payout and refund has an idempotency key; a PayPal timeout is
   recorded as "unknown", never retried blindly.
9. **The app is locked** with the phone's PIN, pattern, fingerprint or face on every open and
   after 15 seconds away. The login is stored encrypted by the Android Keystore and lasts until
   Log out; the server stores only a hash of it.
10. **Owner and customer roles.** Only the account owner (Log in with PayPal, not just a typed
   email) can send from the PayGuard wallet, refund or see its balance. Everyone can pay friends
   from their own PayPal, track autopays and orders, and request refunds.
11. **Prices come from the server**, never from the app; webhooks are verified with PayPal;
    phone calls are verified with Twilio's signature. Coming back from PayPal proves nothing by
    itself: the server reads the real autopay or payment status from PayPal.

## Architecture

```
 Android app (React Native + Kotlin)         Server (FastAPI, Render)            Services
 ─────────────────────────────────────        ───────────────────────────         ─────────────────
 Tabs: Home, Chat, Shop, Send,       HTTPS    /api/chat  ──► Gemini (tool choice)  Google Gemini
       Track, Profile               ───────►  chat_flow: safety, grounding,        Gemini Live
 Live voice: mic 16 kHz ⇄ voice 24 kHz WSS    roles, scam guard, limits
   (OkHttp, echo cancel, loudspeaker) ─────►  /api/live ⇄ Gemini Live              PayPal REST APIs
 Keystore: signing key + login safe           payouts / refunds / orders /  ─────► (Orders, Payouts,
 BiometricPrompt (fingerprint/PIN)            balances / login / webhooks          Refunds, Balances,
                                              PostgreSQL (Neon)                    Identity, Webhooks)
 Browser opens only paypal.com;               /api/phone (Twilio, signed) ◄─────── Twilio voice
 PayPal returns into the app                  catalog proxy ─────────────────────► DummyJSON demo store
```

## Run it

Backend (Python 3.11, PostgreSQL):

```bash
cd backend
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env    # fill in PayPal sandbox keys, Gemini key, database, JWT secret
.venv\Scripts\python -m uvicorn app.main:app --port 8000
.venv\Scripts\python -m pytest tests
```

Android app (Node 22+, Android SDK):

```bash
cd apps/mobile
npm install
cd android
gradlew app:assembleRelease
```

The app talks to the server address in `apps/mobile/src/api.ts`. PayPal dashboard setup:
enable Log in with PayPal and add `accessiblecommerce://auth/paypal` as a Return URL; create a
webhook to `/api/webhooks/paypal` and put its ID in `PAYPAL_WEBHOOK_ID`.

## Honest limits

- **Sandbox only.** All money is PayPal sandbox test money.
- **Log in with PayPal proves who someone is; it does not open their personal wallet.**
  Payments are sent from the one PayPal business account the app manages, and history covers
  payments made through PayGuard. PayPal cannot read a bank account balance; the balance shown
  is the PayPal wallet's.
- **The shop's products come from DummyJSON**, a free public demo store (search, ratings,
  reviews). A real shop would plug in its own catalog.
- **Phone-call ordering** is built and tested but needs a paid Twilio number to run.
- **Autopays with other companies can't be read.** PayPal does not let any app see a person's
  subscriptions with other merchants, so PayGuard tracks real PayPal autopays started in
  PayGuard (demo billers in the sandbox; one renews daily) and outside autopays you add by
  hand. Reminders are made when the app checks for alerts (the free server has no clock job).
- **Deliveries** show the shop's expected date; there is no live courier tracking in the demo.
- **Best products** come from Google Shopping through SerpAPI (free plan: 100 searches a month,
  cached 6 hours). PayGuard only links to the stores; it never orders from them. Prices,
  ratings and links come from the search results, never from the AI.
- **Paying from your own PayPal** always opens PayPal's page to approve: PayPal does not let
  any app move a person's own money with only a fingerprint.

## Go-live plan (after the hackathon)

1. Verified PayPal Business account (note: PayPal India does not support payments between
   Indian accounts, and Payouts needs PayPal's approval).
2. Live app in the PayPal developer dashboard; approval for Payouts; Log in with PayPal app
   review (real privacy policy and terms pages).
3. Live webhook; on the server set `PAYPAL_ENV=live` with live keys (mixed live/sandbox
   settings refuse to start, so test and real money cannot mix).
4. Replace the demo catalog with real products; test with $1; keep the limits.

## License

MIT
