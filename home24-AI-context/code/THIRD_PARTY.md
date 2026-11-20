# Third-party notices

Home24 bot uses and adapts ideas/code under permissive licenses:

| Component | License | Notes |
|-----------|---------|--------|
| [Telethon](https://github.com/LonamiWebs/Telethon) | MIT | MTProto client |
| [opentele-ng](https://github.com/stufently/opentele) | MIT | tdata → Telethon (`UseCurrentSession`); adapted in `bot/tdata_import.py` |
| Web login UX ideas | MIT (various) | Inspired by tele-auto-gram / telegram-mcp patterns; reimplemented in `bot/web_login.py` |
| Outreach caps / FloodWait respect | ideas only | Inspired by telegram_crm-style reliability; our code in `bot/rate_limit.py` |

Unlicensed or unclear-license repositories were used only as product ideas, not as source copies.
