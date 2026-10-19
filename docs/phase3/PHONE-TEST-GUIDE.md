# Phase 3 real-phone test guide

For the owner: this Mac plus one Android phone or iPhone on the **same trusted Wi-Fi** (home or office, not public Wi-Fi). It takes about 20 minutes and costs ₹0.

**What it uses:**
- an isolated database `routewise_phone` with synthetic customers on public DU North Campus points;
- a plan computed on your **local** Valhalla tiles.

**What it does not touch:** your development database, real customer data, any public tunnel, deployment, router setting or paid service. PostgreSQL stays bound to 127.0.0.1; only the app is reachable, and only on your Wi-Fi.

**Keep out of the repository:** the passwords, the Mac's network address and your phone number. Don't paste them into results, screenshots or commits.

## A. Start (on the Mac, in Terminal, from the RouteWise folder)

1. Build the test data:
   ```bash
   scripts/dev-db.sh create-db routewise_phone   # first time only ("already exists" is fine)
   services/api/.venv/bin/python services/api/scripts/phone_setup.py
   ```
   - When asked "Number for the Call check", type a number **you control** (for example your own). The input is hidden and stored only in `routewise_phone`. Press Enter to skip; you can set it later in Orders.
   - Messages about "leaked function" at the end come from the routing library and are harmless.
   - Running this again resets `routewise_phone` with fresh passwords.
2. Open the two local files it wrote (git-ignored, readable only by you):
   - `.local/phone/credentials.txt`: user names and passwords;
   - `.local/phone/expected.txt`: Test Rider A's stops in order, each with its public place, pin, expected Google Maps link and contact.
3. Start the server: `scripts/phone-server.sh`. It prints `Open on the phone: http://<address>:8020`.
   - Leave this window open.
   - If macOS asks whether Python may accept incoming connections, choose **Allow**. That allows the local network only; no router change is needed.

## B. Phone access

4. Connect the phone to the same Wi-Fi.
5. Open the printed address in the phone's browser (Chrome on Android, Safari on iPhone). Type it; don't share it.
6. Sign in as `phone_rider_a` with the password from `credentials.txt`.

## C. Checks (record each in [PHONE-TEST-RESULTS.md](PHONE-TEST-RESULTS.md) as PASS, FAIL or NOT RUN)

7. **Own list.**
   - **Shows:** "My deliveries" lists one round with Test Rider A's stops in the order of `expected.txt`, numbered "Stop 1 … Stop 4", with Stop 1 marked **Next**.
   - **Does not show:** none of the order codes listed for Test Rider B.
   - **Details:** customer, product, contact and (where present) delivery instructions are readable.
8. **Call (number you entered).**
   - On Stop 1, tap **Call**. The dialer (Android) or call prompt (iPhone) must show the number you entered.
   - **Do not place the call:** press back or Cancel.
   - If you skipped the number at setup: on the Mac, sign in as `phone_admin` at the same address, open **Orders**, edit Stop 1's order, set Contact to your number and save. Then on the phone tap **Refresh** and repeat.
9. **Call (synthetic contacts).**
   - Do **not** tap Call on any other stop; those contacts (`0000000002` …) are placeholders.
   - Only check that the contact text shown matches `expected.txt`.
10. **Navigate.**
    - On Stop 1, tap **Navigate**. Google Maps (app or browser) must open directions to the **place and pin in `expected.txt` for Stop 1**.
    - Compare the destination name or pin. Google may show a nearby address for the same point.
    - Starting navigation is not needed. Note whether the travel mode was two-wheeler.
    - Repeat for one more stop. Nothing should open until you tap.
11. **Postpone.**
    - On Stop 1, tap **Postpone**: "saved as Postponed" appears.
    - The order moves to **Postponed**, and Stop 2 becomes **Next**.
12. **Return to Pending.** On that order, tap **Return to Pending**: it goes back to Stop 1 as **Next**.
13. **Mark delivered.**
    - On Stop 2, tap **Mark delivered**. A confirmation appears; tap **Yes, delivered**.
    - It moves to **Completed** with no Call, Navigate or status buttons.
14. **Refresh.** Tap **Refresh**: the same statuses remain.
15. **Persistence.**
    - Tap **Sign out**, sign in again as `phone_rider_a`: the statuses are unchanged.
    - Optional: on the Mac, as `phone_admin`, the **Orders** page shows the same statuses.
16. **Other rider (optional).** Sign out, sign in as `phone_rider_b`: only Test Rider B's orders appear, never Rider A's.
17. **Touch and readability.** Buttons are easy to tap, text is readable without zooming, and nothing needs sideways scrolling.

## D. Shut down

18. In the server window press **Ctrl+C**. The app stops listening on the Wi-Fi address.
19. Optional: stop the database with `scripts/dev-db.sh stop`, and delete `.local/phone/` to remove the test passwords. `routewise_phone` holds only synthetic data; the next setup resets it.
20. Fill in [PHONE-TEST-RESULTS.md](PHONE-TEST-RESULTS.md) (or the template below in a message) and send it back. Use phone model, OS and browser only: no phone number, address, password or screenshot showing them.
