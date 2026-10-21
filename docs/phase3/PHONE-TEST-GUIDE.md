# Phase 3 real-phone test guide

For the owner: this Mac plus one Android phone or iPhone on the **same trusted Wi-Fi** (home or office, not public Wi-Fi). It takes about 20 minutes and costs ₹0.

**What it uses:**
- an isolated database `routewise_phone` with synthetic customers on public DU North Campus points;
- a plan computed on your **local** Valhalla tiles.

**What it does not touch:** your development database, real customer data, any public tunnel, deployment, router setting or paid service. PostgreSQL stays bound to 127.0.0.1; only the app is reachable, and only on your Wi-Fi.

**Keep out of the repository:** the passwords, the Mac's network address and your phone number. Don't paste them into results, screenshots or commits.

## A. Start (on the Mac, in Terminal, from the RouteWise folder)

**Already have a `routewise_phone` from an earlier test? Do A0 first.** Starting fresh? Go to step 1.

### A0. Bring an existing phone database up to date (since step 4B)

Step 4B added database migration `0005` and step 4C migration `0006`. A `routewise_phone` built before them is still on schema `0004`. The newer code cannot read it: sign-in or the rounds screen breaks with `column round_riders.route_version does not exist`. The upgrade below applies every missing migration.

`scripts/phone-server.sh` now checks the schema before it builds or serves anything. If the database is out of date it prints the steps below and **does not start**. It never resets, rebuilds or migrates anything by itself.

a. Stop the phone server if it is running (**Ctrl+C** in its window).

b. Look (read-only, changes nothing):
   ```bash
   services/api/.venv/bin/python services/api/scripts/phone_db.py check
   ```
   `Database routewise_phone: schema 0006 (current).` (or the newest migration's number) means you can go to step 3. Otherwise it says what to do.

c. **Upgrade and keep the data** (riders, passwords, orders, plan, statuses). You run this yourself:
   ```bash
   services/api/.venv/bin/python services/api/scripts/phone_db.py upgrade
   ```
   - It touches only `routewise_phone` and refuses any other database name. The development and test databases, and any other server, are not touched.
   - It only adds columns and tables. Existing rows are kept, and each migration is one transaction, so a failure leaves the database as it was.
   - The passwords in `.local/phone/credentials.txt` stay valid. You do not need to run `phone_setup.py`.
   - Orders marked Completed before the upgrade have no completion time. A later reroute never uses them as the "last completed stop".

d. Start the server (step 3).

**Alternative, fresh data:** `phone_setup.py` (step 1) rebuilds `routewise_phone` and issues new passwords. That **deletes** what is in it, which is why the launcher never does it for you.

**What 4B and 4C change on the phone:** nothing you can see by themselves. **Step 4D** (the rider screens for them) adds a "Recalculate my route" section and shared-stop containers to the rider page; the Phase 3 checks in C still apply, and the 4D checks are in E. **Phone GPS has not been tested.** Device-position reroutes are covered only by automated tests with MOCKED geolocation.

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
   - If it stops with "The phone-test database routewise_phone is on schema …", follow A0.
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

## E. Optional, step 4D: recalculating the route, and GPS over USB (localhost mode)

**The one fact to know first.** A phone's browser shares its GPS position only with a **secure** page (HTTPS, or `http://localhost`). The Wi-Fi address of step A (`http://<address>:8020`) is **not** secure, so **location never works there**: the app says "Location isn't available on this connection" and offers the other starting points. Wi-Fi mode is fine for everything in C and for the non-GPS checks below. A real GPS check needs localhost mode.

### E1. Localhost mode (only for the GPS check; you run every step yourself)

Needs: a USB cable, USB debugging enabled on the phone, and Android's `adb` (free Android platform-tools) on this Mac. **RouteWise does not install anything, enable debugging, connect a device or run `adb` for you.**

1. Stop the Wi-Fi-mode server if it is running (**Ctrl+C**).
2. Start localhost mode: `scripts/phone-server.sh localhost`. It binds **only** to this Mac's loopback (`127.0.0.1:8020`), allows exactly the origin `http://localhost:8020`, and uses the same `routewise_phone` database and the same schema check as Wi-Fi mode (it still refuses an out-of-date database and never resets or migrates anything). `scripts/phone-server.sh localhost --print-config` shows what it would use and starts nothing.
3. With the phone connected by USB and debugging allowed, run on this Mac: `adb reverse tcp:8020 tcp:8020`.
4. On the phone (Chrome), open `http://localhost:8020` and sign in as in B.
5. When finished: **Ctrl+C** the server, and `adb reverse --remove tcp:8020` (or unplug the phone).

Nothing is public: no tunnel, no router change, nothing listens on the network.

### E2. 4D checks (record each as PASS, FAIL or NOT RUN)

Use **localhost mode** for 1 and 2, and either mode for the rest. **Real GPS can succeed only while the phone is inside the DU North Campus service area** (the area local routing covers); anywhere else, record the refusal message instead.

1. **Location granted.** Tap **Recalculate my route…**, then **Use my current location**, allow location when Chrome asks. Expect "Route recalculated from your current position (device location)" with a time, and your stops in a new order. Nothing was read before you tapped. *Indoors the fix is often less accurate than 100 m: then expect the "not accurate enough" message and record it (the fallbacks below are the normal path).*
2. **Location denied.** Block location for the site, tap **Use my current location**: expect the denied message and that nothing changes until you pick another starting point.
3. **Wi-Fi mode, no GPS.** In Wi-Fi mode the location button is disabled with "Location isn't available on this connection". Recalculating from another starting point still works.
4. **Last completed stop.** Mark a stop delivered, then open the chooser: **From my last completed stop** appears, labelled "Not your current position"; the configured start is not offered. Use it.
5. **Configured start.** With no completed stop, **From the Office/Warehouse (my configured start)** is offered, labelled "Not your current position".
6. **Postpone, then choose.** On the next customer tap **Customer unavailable**: the page offers **Keep current order** or **Recalculate my route**; nothing recalculates by itself.
7. **Shared stop** (the admin must have grouped two orders on the Orders page and re-optimized): one stop with "2 customers at this location" and **one** Navigate; each customer has their own Call and status buttons; delivering one leaves the other in the stop.
8. **Destination change.** Change your Home location (or destination), confirm, and see "still ends at the previous destination until you recalculate"; then recalculate. Another rider's screen is unaffected.
9. **Offline.** Turn on airplane mode: **Recalculate my route…** is disabled with an explanation.
10. **Touch and readability.** Buttons are easy to tap and nothing needs sideways scrolling.

Record phone model, OS and browser only: no coordinates, phone number, address or password.
