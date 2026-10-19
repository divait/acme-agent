# Browser client — manual QA script

Run on Chrome desktop, Safari desktop and Chrome on Android, once with the browser language
set to Spanish and once to English. Use `http://localhost:8000` (`uv run acme-agent serve`);
for Android use a tunnel or the Cloud Run URL with `ACME_ALLOWED_ORIGINS` set.

## A. Full interview by voice
1. Load `/`: branding, "Demo, fictional company" tag, privacy note, *Start interview*. No console errors.
2. Click *Start* and allow the microphone. "Connecting…" shows until Ana greets you (audio and caption, ≤ ~12 s).
3. Say yes to consent: the row shows ✓ Yes/Sí and the progress bar moves.
4. Say you want to be a delivery rider: licence and vehicle rows appear. Correct it to kitchen: they hide.
5. Give your name and phone, then a wrong email and correct it: "!" then ✓.
6. Name a store ("Chamberí"): the row shows "Acme Burgers Chamberí". Answer the rest; every row shows readable text.
7. Confirm Ana's read-back. Her goodbye plays to the end, then the summary shows.
8. The summary shows only the neutral thank-you line; *Demo: recruiter view* is collapsed and shows a neutral status pill.
9. Captions: partial text updates in place, then becomes fixed. Nothing scrolls sideways.

## B. Barge-in
Ask "¿cuánto se cobra?" and talk over the answer: Ana stops within ~300 ms. Three times on speakers,
three on earbuds; Ana must not interrupt herself through echo.

## C. Declined consent
Say "no" to consent: Ana says goodbye in full; the summary says nothing was stored. The record in
`data/` holds only metadata, the consent answer and `declined_consent`.

## D. End button
Press *End interview* mid-sentence: Ana stops at once, then the summary. Closing the tab mid-interview
leaves a record with an end reason.

## E. Errors
- Block the microphone in site settings, then *Start*: the allow-microphone message shows.
- Stop the server, then *Start*: the "could not reach" message shows.
- Kill the server or Wi-Fi mid-interview: "connection lost", and *Start a new interview* opens a fresh session.

## F. Accessibility
- Keyboard only: Start, text box, Send, End, the recruiter-view toggle and *Start a new interview*, focus always visible.
- VoiceOver / TalkBack read finished turns only, not every partial update.
- Reduced motion: the spinner does not spin. Light and dark themes are both readable.
- 375 px width: no horizontal scroll.

## G. Typed input
Type an answer in the text box: Ana replies and the matching row fills.
