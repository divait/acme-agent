# Demo script

A 4 to 6 minute walkthrough of Acme Agent. It uses three calls (one long, two short) and a
terminal. Candidate lines are given in Spanish; say them naturally, wording can vary.

## Setup checklist

- [ ] Headphones on (prevents Ana hearing herself), quiet room, microphone allowed in Chrome.
- [ ] Fresh credentials: `gcloud auth application-default login` (and quota project set).
- [ ] `.env` has `GOOGLE_CLOUD_PROJECT` and `GOOGLE_CLOUD_LOCATION`.
- [ ] Server freshly restarted: `make serve`, then open http://localhost:8000.
- [ ] Hard reload the page (Cmd+Shift+R) so no stale client code is cached.
- [ ] Optional: clear old records (`rm data/conversations/*.json`) so `list` and `stats` are clean.
- [ ] Screen recording at 1280x800 or larger; terminal font large enough to read.
- [ ] Do one throwaway call first to warm the model (the first greeting can take about 10 s).

## Scene 1: landing and language selector (about 20 s)

Show the landing page and the language selector. Select **Español**.

Point out: the "Demo, fictional company" tag, the privacy note, one clear *Start* button.

## Scene 2: happy path as a rider, in Spanish (about 90 s)

Click *Start* and allow the microphone. Wait for Ana's greeting.

| Candidate says | Point out |
|---|---|
| "Sí, doy mi consentimiento." | Consent row turns into a check; progress bar moves |
| "Quiero trabajar de repartidor." | Licence and vehicle rows appear |
| "Me llamo Lucía Gómez." | Name fills in live, captions stream |
| "Mi teléfono es el 612 34." (stop) then "perdón, 612 345 678" | An invalid or incomplete phone is rejected and re-asked, then accepted |
| "Puedo empezar el día 5 de... no, mejor el día 3." | The correction overwrites the earlier value |

Point out: the orb changes colour between listening (blue) and speaking (red); the profile
panel fills as answers arrive; several answers in one sentence are all captured.

## Scene 3: FAQ in the middle of the flow (about 30 s)

When Ana asks the next question, interrupt with: "Espera, ¿cuánto se cobra?"

Point out: barge-in (Ana stops), the answer comes from the FAQ, and Ana returns to the exact
question that was pending instead of restarting.

## Scene 4: switch to English (about 30 s)

Continue the answers, then say: "Sorry, can we continue in English?"

Point out: Ana switches language mid-call, the captions follow, and previous answers are kept.
Answer the next question in English, for example "I can work about thirty hours a week."

## Scene 5: read-back, goodbye and summary (about 60 s)

Answer the remaining questions (store "Chamberí", right to work "yes"). Ana reads the whole
profile back. Say "Yes, that's right."

Point out: Ana finishes her goodbye before the page changes. The page shows "Processing…", then
the neutral thank-you summary for the candidate. Expand **Demo: recruiter view**: screening
status, headline, key points, next steps, and any human-review flags from the post-call
reconciliation.

## Scene 6: declined consent (about 30 s)

Click *Start a new interview*. When asked for consent, say "No." Ana confirms the choice; say
"No, prefiero que no." again.

Point out: Ana confirms, says goodbye in full, and nothing but the consent answer is stored.

## Scene 7: frustration and escalation (about 45 s)

New interview, consent "Sí". Then express frustration twice, for example "Esto es muy lento, ya
me estoy cansando" and "Otra vez lo mismo, qué desesperante". Ana offers a recruiter. Say "Sí,
prefiero hablar con una persona."

Point out: the sentiment monitor ran in the background, the offer was made once, and the
recruiter view shows the conversation as escalated.

## Scene 8: terminal (about 40 s)

```bash
uv run acme-agent list           # newest first, with status and end reason
uv run acme-agent show <id>      # full record of the first call
uv run acme-agent stats          # counts, completion rate, median duration, failed slots
```

Point out: the record contains the profile with per-field metadata, transcript, events
(corrections, language switch, FAQ answered, escalation), sentiment and summary.

## If something goes wrong

- Credential error: re-run the ADC login and restart `make serve`.
- Ana cuts herself off: switch to headphones.
- No audio on first load: hard reload, click *Start* again, check the microphone permission.
- A slow greeting on the first call is a cold start; trim it when editing.
