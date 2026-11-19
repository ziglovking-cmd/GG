# Пакет сдачи специалисту → заказчику

Отправляйте заказчику **без** `.session` / прокси / api_hash / токенов.

## Порядок отправки

1. `CLIENT_LETTER.md` — сопроводительное письмо  
2. `TZ_CONCLUSION.md` — письменное заключение  
3. `CHANGELOG_TZ.md` — что изменено в коде  
4. `ACCEPTANCE.md` — чеклист приёмки  
5. Ссылка на PR / архив кода  
6. Видео: `tz_delivery_walkthrough_slides_and_pytest.mp4` (слайды + pytest)  
7. При созвоне: `CONSULTATION_AND_COST.md` + `VIDEO_SCRIPT.md` + `delivery_presentation.html`

## Смета (озвучить)

- A консультация — **35 000 ₽**  
- B внедрение — **140 000 ₽**  
- **A+B = 175 000 ₽**  
- C опционально — 180 000 ₽  

## Локально открыть слайды

```bash
cd exports && python3 -m http.server 8765
# http://127.0.0.1:8765/delivery_presentation.html
# автопрокрутка: ?auto=7500
```
