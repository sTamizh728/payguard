# Devpost submission text for PayGuard

Copy each section into the matching Devpost field.

## Project name
PayGuard: talk to PayPal

## Elevator pitch (one line)
A voice-first mini PayPal in English and Tamil: talk to send money, shop, set up and track
autopays and deliveries. Money moves only after your PIN + fingerprint or PayPal checkout, never the AI.

## Inspiration
Paying online assumes you can see a screen, read small print and spot a scam. Many people
can't: blind and low-vision users, older people, and people more comfortable speaking Tamil
than reading English. I wanted a PayPal assistant you can simply
talk to, and that protects you better than a screen does: it should never let an AI, a
scammer or a stolen phone move your money.

## What it does
PayGuard is an Android app with a real two-way voice conversation (Gemini Live), plus chat
and buttons for everything:

- **Shop by voice:** search products, hear prices, ratings and real reviews, add to cart, pay
  in PayPal checkout, then get an order confirmation, expected delivery date and a receipt
  with the PayPal transaction ID.
- **Send money:** "Send $20 to Priya" uses PayPal Payouts after a scam check, your own
  PayGuard PIN and your fingerprint. Anyone can also pay a friend from their own PayPal
  (approved on PayPal's page).
- **Autopay:** "Set up autopay for StreamBox" starts a real PayPal subscription; PayGuard
  shows the next charge and last payment, alerts on every charge or failure, and pauses,
  resumes or cancels it by voice. Autopays set up elsewhere can be added for reminders.
- **Track:** one tab for payment history, autopays, shop orders and expected deliveries,
  also by voice ("show my payment history", "where is my order?").
- **Stay informed:** "Did any payment fail?", PayPal balance behind a fingerprint, and
  real-time alerts from verified PayPal webhooks (money received, payment returned, disputes).
- **Refunds:** owners refund in part or in full; customers ask for refunds by voice and the
  owner approves.
- **Log in with PayPal**, your own PayGuard PIN, the app locked by the phone's PIN or fingerprint on every open, and
  a phone-call ordering menu (English and Tamil) ready for a Twilio number.

## How we built it
- **App:** React Native 0.88 for Android, plus my own Kotlin module: an Android Keystore
  signing key unlocked by BiometricPrompt (fingerprint, face or PIN), encrypted login storage,
  designed chimes, and live audio streaming (16 kHz mic, 24 kHz voice, echo cancellation).
- **Server:** Python FastAPI on Render with PostgreSQL on Neon.
- **AI:** Gemini 3 Flash with function calling for chat, Gemini Live
  (gemini-3.1-flash-live-preview) for voice. The AI only chooses a tool; my code runs it.
- **PayPal:** Orders v2 (shop and pay-a-friend), Payouts, Subscriptions, Payments v2 refunds,
  Balances (Reporting), Log in with PayPal (OpenID Connect), Webhooks with signature verification.
- **Also:** Twilio Voice (signed requests) for phone ordering, DummyJSON as a demo catalog.
- **296 automated tests** with PayPal, Gemini, Twilio and the database faked.

## Safety design
- Names, amounts and numbers must come from the person's own words, never the AI's.
- Prompt-injection phrases are blocked in code before the AI sees them, typed or spoken.
- Every payout, refund and autopay change needs your own PayGuard PIN (Argon2-hashed, locks
  after 5 wrong tries) AND a signature from the phone's secure hardware, verified by the
  server: a stolen login, a replayed signature or a spoken "yes" cannot move money.
- Coming back from PayPal proves nothing: the server reads the real status from PayPal.
- A scam guard (new recipient, pressure words, big amounts, rapid payments) locks Confirm for
  30 seconds, enforced by the server.
- Limits, idempotency keys, and "unknown" instead of blind retries on timeouts.

## Challenges we ran into
- **Chrome flagged the free server address as "dangerous"** (a "pay" name that sends people to
  PayPal's login looks like phishing to its filter). I redesigned the flows so the browser only
  ever opens paypal.com, and PayPal returns straight into the app.
- **Gemini Live on a phone:** routing audio to the loudspeaker, echo cancellation, and stopping
  the assistant from hearing and interrupting itself.
- **PayPal's app account can't use Log in with PayPal on its own app**, and the demo catalog
  only matched exact words. Both needed rethinking.
- **Building solo in about two weeks** while keeping the code small and tested.

## Accomplishments that we're proud of
A real voice conversation that can shop and pay, where the AI still can never move money.
The whole flow works for a screen-reader user, with sounds that say what happened.

## What we learned
Give the AI as little power as possible: let it understand, and let plain code decide. And
the safest confirmation is one the server can verify cryptographically, not a button.

## What's next for PayGuard
Go live with real PayPal (Payouts approval and app review), a real merchant catalog, live
courier tracking, phone ordering with a Twilio number, and more Indian languages.

## Built with
react-native, kotlin, android, python, fastapi, postgresql, gemini, gemini-live, paypal,
paypal-orders, paypal-payouts, paypal-subscriptions, paypal-webhooks, twilio, render, neon

## Links
- Code: https://github.com/sTamizh728/payguard
- Video: (your YouTube link)
