# Phase 3 real-phone test results

**Status: owner-reported results recorded (19 Oct 2026); the functional checks passed on the original UI and the visual check of the polished cards (V1) passed.** Phase 3 is accepted for local development on this basis ([record](OWNER-ACCEPTANCE-2026-10-19.md)). The owner ran the checks in [PHONE-TEST-GUIDE.md](PHONE-TEST-GUIDE.md) on a real phone and reported the outcome to Claude Code in a message. These are **owner-reported device results**: they were not automated, and no one else observed them. Claude Code did not see the phone, its screen or the server session. Each result below records only what the owner reported. Details the owner did not supply are marked **not supplied**, and checks the owner did not report are marked **NOT REPORTED**. Nothing has been inferred as passed.

Do not record passwords, the Mac's network address, phone numbers, real addresses, or screenshots showing any of them.

| Field | Value |
|---|---|
| Date and time | Not supplied (results reported on 19 Oct 2026; exact test time not supplied) |
| Tester | owner |
| Phone model and OS version | OnePlus Nord 5; OS version not supplied |
| Browser and version | Chrome; version not supplied |
| Google Maps (app or browser) | Not supplied |
| RouteWise commit tested | Not supplied (when the results were reported, `main` was at `46b17ab` with the phone tooling uncommitted) |
| Setup completed (`phone_setup.py` ran; plan on local tiles) | Not separately reported; the owner saw four planned Pending deliveries for Rider A |

| # | Check (guide step) | Expected | Result | Notes (owner-reported unless stated) |
|---|---|---|---|---|
| 1 | Sign in as Test Rider A (6) | Lands on "My deliveries" | PASS (owner-reported) | Sign-in not described separately; the owner reported seeing Rider A's deliveries list |
| 2 | Own list (7) | Rider A's stops in `expected.txt` order, Stop 1 = Next; no Rider B order codes; details readable | PASS (owner-reported) | "Four Pending deliveries in the expected order; Stop 1 marked Next." The absence of Rider B codes and the readability of details were not reported separately |
| 3 | Call, own number (8) | Dialer/prompt shows the number entered at setup; call **not** placed | PASS (owner-reported) | "Call opened the dialer with the expected number." Whether a call was placed was not reported |
| 4 | Synthetic contacts not dialled (9) | Contact text matches; Call not tapped | NOT REPORTED | |
| 5 | Navigate, Stop 1 (10) | Google Maps directions to Stop 1's place/pin; opened only on tap | PASS (owner-reported) | "All four Navigate links opened the correct destinations." Travel mode shown: not supplied |
| 6 | Navigate, second stop (10) | Directions to that stop's place/pin | PASS (owner-reported) | Covered by "all four Navigate links" (Stops 1–4) |
| 7 | Postpone (11) | "saved as Postponed"; moved to Postponed; Next moves to Stop 2 | PASS (owner-reported) | "Postpone moved Stop 1 out and made Stop 2 Next." The "saved as Postponed" message was not reported separately |
| 8 | Return to Pending (12) | Back at Stop 1 as Next | PASS (owner-reported) | "Return to Pending restored Stop 1 as Pending/Next." |
| 9 | Mark delivered (13) | Second tap required; Completed without buttons | PASS (owner-reported) | "Stop 2 moved to Completed without action buttons." The confirmation (second tap) step was not reported separately |
| 10 | Refresh (14) | Statuses unchanged | PASS (owner-reported) | "Statuses persisted through refresh" |
| 11 | Sign out and sign in again (15) | Statuses unchanged (persisted on the server) | PASS (owner-reported) | "…and sign-out/sign-in." The optional admin Orders check was not reported |
| 12 | Other rider (16, optional) | Rider B sees only their own orders | NOT RUN / NOT REPORTED | Optional; not reported, so not passed |
| 13 | Touch and readability (17) | Easy to tap, readable, no sideways scrolling | NOT REPORTED as pass/fail; feedback given | "Experience felt smooth." Feedback: "delivery cards need clearer visual presentation". Tap targets and sideways scrolling were not reported separately |
| 14 | Shut down (18) | Server stopped with Ctrl+C | PASS (owner-reported) | "Test server was stopped." Deleting `.local/phone/` (optional) was not reported |

**Problems seen** (what you did, what you expected, what happened):

- No functional failure reported.
- Feedback: the delivery cards need clearer visual presentation. The UI tested on the phone was the **original** card design (before the polish below).

## Follow-up: delivery-card clarity polish (19 Oct 2026)

**What changed:**
- In response to the owner's feedback, the rider delivery cards were restyled (frontend only, no behaviour change). See [PHASE3-REPORT.md §6](PHASE3-REPORT.md#6-delivery-card-clarity-polish-after-the-phone-test).
- Automated checks pass.
- New screenshots: `screenshots/cards/`.

**What the phone results cover:**
- The functional checks above (#1–#14) were made on the **original** UI and are kept as recorded.
- The owner then reviewed the polished cards (V1); the device used for that review was not stated. V1 is a visual check; no repeat of the functional checks on the polished cards was reported. The card polish changed no behaviour, and the automated browser suite covers it.

| # | Check | Expected | Result | Notes |
|---|---|---|---|---|
| V1 | Polished cards, owner's visual check (suggested: guide steps 1–6, look at the cards, optionally repeat 11–13, then shut down with step 18) | Stop/Next, customer and product are easy to tell apart; status badge is clear; instructions and contact are clearly labelled; Call/Navigate are visibly separate from the status buttons; Completed cards are compact but readable; nothing needs sideways scrolling | PASS (owner-reported) | The owner reviewed the polished cards and confirmed they are "clear and good". The device used for this review, test time, versions and which steps were repeated were not supplied |
