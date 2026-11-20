# Attribution

TG Audience reimplements selected **operational patterns** from MIT-licensed
open-source Telethon tools. We do **not** vendor those repositories wholesale.

## References

| Project | License | Ideas adapted |
|---|---|---|
| [ivanchik-byte/tg-invite-machine](https://github.com/ivanchik-byte/tg-invite-machine) | MIT | Trimodal / humanized delay jitter; speed profiles; pre-invite chat reading; `@SpamBot` audit classification; fair account carousel ordering |
| [evilbream/Telegradd](https://github.com/evilbream/Telegradd) | MIT | Conservative flood/pause handling around invite RPCs; session/proxy isolation mindset |
| [SoCloseSociety/Telegram_ScrappingAdding_toGroup](https://github.com/SoCloseSociety/Telegram_ScrappingAdding_toGroup) | MIT | Wave/campaign templates and daily caps idea (reimplemented with presence-confirm + minute-scale gaps; no aggressive 30–75s adder) |

## What we intentionally did **not** copy

- Bulk adder loops, DM spam of invite links, or any bypass of Telegram limits
- Mobile-proxy rotation “farms” or fingerprint auto-rotation tooling
- Whole modules / bots / CLI UIs from the upstream projects

Patterns above are reimplemented inside this codebase under our own architecture
(FastAPI + presence-confirmed invites + SQLite WAL).
