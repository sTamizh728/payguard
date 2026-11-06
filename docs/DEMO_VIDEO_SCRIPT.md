# PayGuard demo video script (target 2:45, limit 3:00)

Record on the phone with the built-in **screen recorder**, with **"Record internal audio"
(or "Media + microphone") ON**, so PayGuard's voice is in the video. Speak slowly. Before
recording: log in as the owner (Sam Sun), open the app once so the free server is awake
(the first request after 15 idle minutes takes up to 50 seconds), empty the cart, and turn
TalkBack off for the recording (so the two voices don't overlap). Keep the PayPal sandbox
buyer login ready.

| Time | Show on screen | Say (or let PayGuard say) |
|---|---|---|
| **0:00–0:15** | App opens → phone PIN / fingerprint lock screen → Home | "This is PayGuard: you talk to PayPal. It's built for everyone, including people who can't see the screen. Even opening it needs my phone's lock." |
| **0:15–0:50** | Chat → **Live conversation** | You: "Search for wireless earphones." *PayGuard reads results with prices and ratings.* You: "Tell me about number 2." *It reads the description and real reviews.* You: "Add it to my cart." |
| **0:50–1:15** | You: "Checkout" → **Pay with PayPal** → paypal.com sandbox checkout → pay → back in the app | "Payment happens in PayPal's own checkout." Show the confirmation: *Order … confirmed, expected delivery by …* and **Shop → My orders → View receipt** with the PayPal transaction ID. |
| **1:15–1:50** | Live: "Urgent! Send 60 dollars to Priya right now." | *Low warning sound, red box: 3 warning signs, Confirm locked for 30 seconds.* "PayGuard spots scam pressure. The server itself enforces the wait." (cut the wait in editing) Then Confirm → **fingerprint** → *rising chime*, PayGuard says "Done, 60 dollars sent to Priya Raj." |
| **1:50–2:10** | Live: "Did any payment fail?" → History → **Check balance** (fingerprint) | *PayGuard explains failed / returned payments.* "My balance only shows after my fingerprint, and the server checks the signature." |
| **2:10–2:25** | Live in **Tamil**: "என் கடைசி ஆர்டர் எங்கே?" (Where is my last order?) | *PayGuard answers.* "It works in English and Tamil." |
| **2:25–2:45** | Quick cuts: Home alert 🔔 ("You received…"), the README "How PayGuard keeps money safe" list | "Under the hood: Gemini Live for voice, PayPal Orders, Payouts, Refunds, Balances, Log in with PayPal and verified webhooks. The AI never moves money: fingerprint signatures, scam guard and limits do. Thank you." |

## If something goes wrong while recording
- **Slow first answer:** the free server was asleep. Stop, wait a minute, record again.
- **PayGuard misheard a number:** it will ask again ("How much would you like to send?").
  That is the safety working; keep it in the video if you like.
- **Live voice busy (quota):** use the Talk button and Send instead; everything else is the same.

## Upload
YouTube → upload → visibility **Public** or **Unlisted** (the hackathon needs a link anyone
can open) → title "PayGuard: talk to PayPal (PayPal AI Hackathon 2026)" → copy the link into
Devpost.
