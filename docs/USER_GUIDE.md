# PayGuard user guide

PayGuard lets you shop, pay and track your money with PayPal by talking or tapping, in
English or Tamil. Every payment is protected by your own PayGuard PIN and your fingerprint.

> PayGuard runs on the **PayPal sandbox**: all money is test money. Nothing here can spend
> real money.

---

## 1. Install the app

1. On an Android phone (Android 9 or newer), open
   **https://github.com/sTamizh728/payguard/releases** and download **PayGuard.apk**.
2. Open the downloaded file. If Android asks, allow **"Install unknown apps"** for your
   browser, then tap **Install**.
3. Make sure the phone has a **screen lock** (PIN, pattern or fingerprint). PayGuard uses it to
   protect payments.

The app talks to an online server, so you don't need a computer. If nobody has used it for a
while, the first screen can take up to a minute to load.

---

## 2. Log in with a PayPal sandbox account

You need a PayPal **sandbox** (test) account, not your real PayPal login. Choose one:

### Option A: use our test accounts (quickest)

| Account | Email | Password |
|---|---|---|
| Buyer 1 | `________________________` | `____________` |
| Buyer 2 | `________________________` | `____________` |
| Shop owner (send from the PayGuard wallet, refunds, balance) | `________________________` | `____________` |

Please don't change these passwords: other testers use them too.

### Option B: use your own sandbox account
1. Go to **https://developer.paypal.com** and log in with any PayPal account.
2. Open **Testing Tools → Sandbox Accounts → Create account**, choose **Personal**, and create it.
3. Open the new account (the **⋮** menu → **View/edit account**) to see its email and password.

### Then, in PayGuard
1. Open PayGuard and unlock it with your phone's fingerprint or PIN.
2. Tap **Log in with PayPal**, enter the sandbox email and password on PayPal's page, and
   agree. PayPal sends you back to PayGuard.
3. **Choose your PayGuard PIN** (4 to 6 digits, not 1234 or 1111). PayGuard asks for it, with
   your fingerprint, before any payment.

You stay logged in until you tap **Me → Log out**. The app locks every time you open it.

---

## 3. What you can do

The tabs at the bottom are **Home, Talk, Shop, Send, Track, Me**.

### Talk (voice)
Tap **Talk → Live conversation** and just speak. Try:
- "Find wireless earbuds"
- "Tell me about number 2", "Add it to my cart", "Checkout"
- "Find the best earbuds under 3000"
- "Show my payment history", "When is my next autopay?"
- In Tamil: "என் கடைசி ஆர்டர் எங்கே?" (Where is my last order?)

Tap the button again to end the conversation. You can also type in the box, or use **Talk**
to speak one message.

### Checkout by voice
1. Say **"Checkout"**.
2. If you have no delivery address yet, PayGuard asks one question at a time: name, street,
   area, city, PIN code (say it digit by digit), country, state and phone. Say **"skip"** for
   area or phone.
3. PayGuard reads the address back. Say **"yes"** to save it, or **"change city"** (or name,
   street, PIN code…) to fix one part. Say **"cancel"** to stop.
4. **First order:** PayPal's page opens; log in and pay. PayPal can save your account.
5. **Next orders:** a Confirm box appears. Type your **PayGuard PIN** and use your
   **fingerprint**. Paid; no PayPal page.

### Shop
- **Best picks:** the best-rated products from online stores (Amazon, Flipkart and others),
  ranked by rating and number of reviews. Add a budget like "under 3000". Tap **Open at
  [store]** to buy on that store's own website, or **Compare prices in all stores**.
- **Shop:** search the PayGuard demo shop, read reviews, add to cart.
- **Cart:** your delivery address and **Pay**.
- **Orders:** your orders and receipts.

### Send
- **Choose who to pay:** a test contact, **Pick from phone contacts**, or **type their PayPal
  email**.
- **My own PayPal:** you approve the payment on PayPal's page.
- **PayGuard wallet (shop owner only):** type the PayGuard PIN, then use your fingerprint.
- **Scam check:** if a payment looks risky (new person, large amount, "urgent"), PayGuard warns
  you and makes you wait 30 seconds before you can confirm.

### Track
- **Payments:** everything you sent, paid and received. The shop owner can also check the
  PayPal balance (PIN + fingerprint).
- **Autopay:**
  - Start a PayPal autopay (demo billers; **Daily News** charges every day, so you see it work
    quickly).
  - Pause, resume or cancel one (PIN + fingerprint).
  - Add autopays you pay elsewhere and get a reminder 2 days before each charge.
- **Orders** and **Deliveries:** the expected delivery date of each order.

### Me
Change your PIN, set up security on a new phone, choose English or Tamil, forget a saved
PayPal, and log out.

---

## 4. Safety in one minute
- The AI only understands what you say. It can never send money by itself.
- Money moves only after your **PayGuard PIN and fingerprint** (checked by the server), or on
  **PayPal's own page**.
- Names, amounts and addresses come from your own words, never from the AI.
- Tricks like "ignore your rules" or "skip the confirmation" are blocked.
- Limits: $100 per payment and $200 a day from the PayGuard wallet.

---

## 5. If something goes wrong

| Problem | What to do |
|---|---|
| First screen is slow, or "could not reach the server" | Wait a minute and unlock again: the free server is waking up. |
| PayPal didn't jump back to PayGuard | Open PayGuard yourself. For an autopay, tap **Track → Autopay → Check again**. |
| "Set up your PayGuard PIN first" | Go to **Me** and set a PIN. |
| Fingerprint prompt doesn't appear | Make sure the phone has a screen lock and a fingerprint set up in Android settings. |
| "Web product search is not set up" / "limit reached" | The free search quota is used up for now. Try again later. |
| Live voice is busy | Use the **Talk** button (one message at a time) or type instead. |

Questions or problems: open an issue at **https://github.com/sTamizh728/payguard/issues**.
