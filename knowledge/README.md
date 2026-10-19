# Knowledge content

All content in this folder is **fictional**. Acme Burgers is an invented company; the stores, addresses, pay figures, contacts and policies do not describe any real business. Emails and URLs use only the reserved `.example` domain.

## `stores.json`

A JSON array of store objects:

| Field           | Description                                         |
|-----------------|-----------------------------------------------------|
| `id`            | Unique kebab-case identifier, e.g. `mad-sol`        |
| `name`          | Display name                                        |
| `city`          | City                                                |
| `area`          | Neighbourhood or area                               |
| `country`       | `ES` or `MX`                                        |
| `address`       | Fictional street and number                         |
| `opening_hours` | Daily opening hours, e.g. `10:00–00:00`             |

The first five fields map to the `Store` domain model; `address` and `opening_hours` are extra information for answers.

## `faq_en.md` and `faq_es.md`

Each file is a list of `## ` sections, one question per section.

- Directly under the heading comes an id comment: `<!-- id: <kebab-id> -->`.
- Each section has at most 80 words, so one chunk answers one question.
- Both languages must contain the same ids in the same order. Translate; do not reorder.
- Street names and numbers in `stores.json` are invented and do not correspond to real places.
- The FAQ does not list store addresses; the assistant names the stores in the candidate's city and the full list is on the (fictional) careers page.
- Shift windows follow the domain rules: morning before 12:00, afternoon 12:00–18:00, night from 18:00. Weekly hours range from 10 to 40; minimum age is 18.
