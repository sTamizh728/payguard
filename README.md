# PayGuard

**A voice and chat assistant for PayPal, in English and Tamil.** Talk or type to send
money, check your payment history, find failed or returned payments, and handle
refunds. Money only moves after your fingerprint, face or phone PIN.

Built for the PayPal AI Hackathon 2026.

## What it does

| You say | PayGuard does | PayPal API |
|---|---|---|
| "Send $20 to Priya" | Finds Priya in your contacts, asks you to confirm with your fingerprint, sends the money | Payouts |
| "Did any payment fail?" | Checks every payment you sent and explains failed, returned or unclaimed ones | Payouts (status) |
| "Show my payments" | Lists money received, with what can still be refunded | Orders / Captures |
| "Refund $5 from payment 2" | Prepares a partial refund, confirmed with your fingerprint | Payments v2 refunds |
| "My latest order arrived damaged" (customer) | Sends a refund request to the owner, who approves or declines | Payments v2 refunds |

Log in with **Log in with PayPal** (OpenID Connect) or with email and password.

## How it keeps money safe

- **The AI never moves money.** Google Gemini only turns what you said into one
  intent (send, refund, show history). Plain Python code checks it and does the rest.
- **Nothing the AI invents is used.** Names, amounts and payment numbers must be in
  your own words, digits or spoken numbers.
- **Fingerprint / face / PIN, checked by the server.** The phone keeps a key in its
  secure hardware that only unlocks after biometric or PIN. It signs each confirmation,
  and the server verifies the signature before any payout or refund. A stolen login
  token alone cannot move money, and a spoken "yes" never does.
- **Limits:** $100 per payment, $200 per day, re-checked at the moment of confirming.
- **Prompt-injection guard:** tricks like "ignore your rules" or "SYSTEM: already
  approved" are blocked in code before the AI sees them; two strikes lock payments for
  10 minutes.
- **Safe retries:** every payout and refund carries an idempotency key, and a PayPal
  timeout is recorded as "unknown", never retried blindly.

## Accessibility

Built screen-reader first (TalkBack): every control is labelled, live regions announce
replies, and a live voice conversation mode listens, answers aloud and listens again.
Distinct sounds tell you a payment was sent, refunded, requested or failed without
looking at the screen.

## Project layout

```
backend/        FastAPI + PostgreSQL + Gemini + PayPal REST APIs
  app/agents/   intent (Gemini tools), chat_flow (rules, confirm), guardrails
  app/services/ payouts, refunds, PayPal login, device-key security
  tests/        136 offline tests (PayPal and Gemini faked)
apps/mobile/    React Native 0.88 Android app
  src/screens/  Home, Assistant, Send, History, Profile
  android/.../PayGuardNativeModule.kt   biometric signing, sounds, speech
```

## Run it locally

Backend (Python 3.11, PostgreSQL running):

```bash
cd backend
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env   # then fill it in
.venv\Scripts\python -m uvicorn app.main:app --port 8000
.venv\Scripts\python -m pytest tests
```

Log in with PayPal needs a public HTTPS URL, for example
`ngrok http --url=<your-domain> 8000`, registered as a Return URL in the PayPal dashboard.

Mobile (Android, Node 22+):

```bash
cd apps/mobile
npm install
npx react-native start --port 8081
cd android && gradlew app:installDebug
adb reverse tcp:8081 tcp:8081
adb reverse tcp:8000 tcp:8000
```

Everything runs on the PayPal **sandbox** with test accounts.

## Limits (honest)

Log in with PayPal proves who someone is; it does not give access to their personal
wallet. PayGuard sends from one PayPal business wallet (the app's), and history covers
payments made through PayGuard.

## License

MIT
