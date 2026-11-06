# PayGuard

**Talk to PayPal.** PayGuard is a voice-first PayPal assistant for Android, in English and
Tamil. Speak naturally (real two-way voice with Gemini Live), or type, to send money, shop,
check payments, get refunds and catch failed payments. **Money only moves after your
fingerprint, face or phone PIN, or in PayPal's own checkout. The AI never moves money.**

Built solo for the PayPal AI Hackathon 2026. Everything runs on the PayPal **sandbox**.

- Backend (live): `https://payguard-api-0msk.onrender.com` (FastAPI on Render, PostgreSQL on Neon)
- App: React Native 0.88 Android app with its own Kotlin module (`apps/mobile`)
- 246 automated tests (`backend/tests`), PayPal, Gemini and the database faked

---

## What you can do

| Say or type | What happens | PayPal API |
|---|---|---|
| "Search for wireless earphones" | Reads the top results with price and star rating | — (demo catalog) |
| "Tell me about number 2" | Description, stock, shipping and real written reviews | — |
| "Add it to my cart", "Checkout" | One multi-item order, paid in PayPal checkout | **Orders v2** (create, capture) |
| "Where is my order?" | Status, expected delivery date, receipt with PayPal transaction ID | Orders v2 |
| "Send $20 to Priya" | Scam check, then fingerprint/PIN, then the money is sent | **Payouts** |
| "Did any payment fail?" | Failed, returned or unclaimed payments, explained | Payouts (status) |
| "Refund $5 from payment 2" | Partial or full refund after the fingerprint | **Payments v2 refunds** |
| "My order arrived damaged" (customer) | A refund request the owner approves or declines | Payments v2 refunds |
| History → Check balance | PayPal wallet balance, after a fingerprint check the server verifies | **Balances (Reporting)** |
| (automatic) | "You received $12.50", "Your payment was returned", disputes | **Webhooks** (+ signature verification) |
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
4. **Fingerprint, face or PIN, checked by the server.** The phone keeps a P-256 key in its
   secure hardware that unlocks only with biometrics or the phone PIN. It signs each
   confirmation; the server verifies the signature before any payout or refund. A stolen login
   cannot move money, a signature cannot be replayed, and a spoken "yes" never moves money.
5. **Scam guard.** A new recipient, pressure words ("urgent", "gift card", "அவசரம்"), a large
   amount or many payments in a row raise warnings. With two or more, Confirm stays locked for
   30 seconds, enforced by the server (even a valid fingerprint cannot skip it).
6. **Limits:** $100 per payment and $200 a day, re-checked at the moment of confirming.
7. **Safe retries:** every payout and refund has an idempotency key; a PayPal timeout is
   recorded as "unknown", never retried blindly.
8. **The app is locked** with the phone's PIN, pattern, fingerprint or face on every open and
   after 15 seconds away. The login is stored encrypted by the Android Keystore and lasts until
   Log out; the server stores only a hash of it.
9. **Owner and customer roles.** Only the account owner (Log in with PayPal, not just a typed
   email) can send money, refund or see the balance. Customers see their own purchases and
   request refunds.
10. **Prices come from the server**, never from the app; webhooks are verified with PayPal;
    phone calls are verified with Twilio's signature.

## Architecture

```
 Android app (React Native + Kotlin)         Server (FastAPI, Render)            Services
 ─────────────────────────────────────        ───────────────────────────         ─────────────────
 Tabs: Home, Chat, Shop, Send,       HTTPS    /api/chat  ──► Gemini (tool choice)  Google Gemini
       History, Profile             ───────►  chat_flow: safety, grounding,        Gemini Live
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
