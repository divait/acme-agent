# Technical Constraints

Durable, non-negotiable boundaries (security, platforms, data ownership).
These are not the current tech stack — see `architecture/tech-stack.md`.

- **Language**: the backend is Python (3.12+).
- **Cloud**: AI models are consumed from Google Cloud Vertex AI (GCP credits fund the
  project); authentication uses Application Default Credentials or a service account —
  never API keys in code, config files committed to git, or the browser.
- **Personal data (GDPR)**: candidate data is personal data. Recording/processing consent
  is asked before anything else; a declined consent stores nothing but the decline.
  Phone numbers and names are masked in logs. Stored records have a configurable retention.
- **AI in hiring (EU AI Act, high-risk)**: no automated rejection; human oversight on every
  outcome; prompt and model versions recorded in every conversation for traceability.
- **Fair screening**: the agent never asks about nationality, religion, health,
  disability, pregnancy, family situation or exact age. Eligibility is asked only as
  yes/no ("right to work", "18 or over").
- **Platform**: candidates use a modern desktop or mobile browser with microphone access
  over HTTPS (or localhost). No native apps.
- **Repository hygiene**: `raw/`, `.env*` (except `.env.example`) and `data/` runtime
  output are never committed.
