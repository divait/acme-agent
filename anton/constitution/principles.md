# Principles

Product and engineering principles every change must respect.

1. **The candidate's time is precious.** One question per turn, short sentences, no
   re-asking what is already known. A change that adds turns needs a reason.
2. **The model talks, the code decides.** The LLM handles language; state, validation,
   ordering and screening outcomes are deterministic Python that can be unit-tested.
3. **Nothing is "saved" unless it was validated.** Data enters the record only through
   validated paths, and anything uncertain is marked as such, never silently guessed.
4. **Humans make hiring decisions.** The system routes and summarises; it never rejects.
   It never asks about protected characteristics.
5. **Grounded or silent.** The agent answers job questions only from Acme's knowledge base
   and says when it does not know.
6. **Keep the hot path clean.** Nothing slow or optional runs between the candidate
   finishing a sentence and hearing Ana; analytics and persistence run beside it.
7. **Testable without a microphone.** Every behaviour that matters can be exercised in
   text mode or unit tests; voice is an adapter.
8. **Configuration over code for business content.** Roles, slots, stores, FAQ and model
   ids are data or settings, so another business or model is a config change.
