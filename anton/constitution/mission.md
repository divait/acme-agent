# Mission

## Why this project exists
High-volume frontline employers (quick-service restaurants, retail, logistics) must
screen large numbers of hourly candidates quickly, at any hour and in the candidate's
own language. Recruiters lose most of their time on repetitive first-contact calls and
on re-typing what candidates said.

Acme Agent is a proof of concept of a **real-time, multilingual voice agent** ("Ana")
that runs a short screening interview for **Acme Burgers**, a fictional fast-food chain
in Spain and Mexico, and turns the conversation into a **validated, structured candidate
record** with a summary a recruiter can act on.

## Intended users
- **Candidates** applying for crew member, kitchen or delivery rider roles, often from a
  phone, often in Spanish, sometimes switching to English.
- **Recruiters** at Acme Burgers who review the resulting records and decide who moves on.
- **Developers** iterating on prompts, flow and validation without speaking to the agent.

## What done means
- A candidate can complete a 3–5 minute voice interview in Spanish or English in the browser,
  with perceived response time around 1–1.5 s.
- Every required field is either validated or explicitly marked unresolved in the stored JSON.
- Each conversation produces a JSON record with transcript, extracted data, events,
  sentiment, summary and a screening status.
- `pytest` passes offline; persona evals report slot precision/recall.
- A recorded demo shows the happy path plus corrections, an FAQ question, a language
  switch and an escalation.

## Non-goals
- No automatic hiring or rejection decisions — a human recruiter always decides.
- No real telephony or WhatsApp channel in the proof of concept (browser microphone only).
- No ATS integration, recruiter dashboard, authentication or multi-tenant admin.
- No support beyond Spanish and English.
