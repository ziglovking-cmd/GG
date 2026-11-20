# Home24 v10.22 · 14.11.2026 — идеальный менеджер + релиз на сервер

## Зачем

1. Владелец: «начальница сказала вот этот диалог был идеальным — настраивайся под него»
   и «сделай его пиздец умным».
2. Нужен готовый ZIP + скрипт выкладки на Ubuntu без ручной возни.

## Что сделано

- В `smart_prompt.txt` возвращён **ЭТАЛОННЫЙ ДИАЛОГ №1** + блок «Идеальный менеджер».
- Новый `bot/ideal_manager.py`: персона + похожие живые реплики из `data/style_dialogs.md`.
- Подмешивание persona/style в system prompt рядом с RAG (`smart.py`).
- Policy-чанки RAG про тон, без повторов и животных.
- `data/ideal_dialog_1.md`, `scripts/pack_server_release.sh`, обновлены `deploy/*`.
- Тесты: `tests/test_ideal_manager.py`.

## Выкладка

```bash
bash scripts/pack_server_release.sh
scp /tmp/home24-release-*.zip root@SERVER:/root/home24.zip
# + data и .env как в deploy/README_SERVER.md
ssh root@SERVER 'bash -s' <<'EOS'
unzip -o -q /root/home24.zip deploy/install_ubuntu.sh -d /tmp/h24inst
bash /tmp/h24inst/deploy/install_ubuntu.sh /root/home24.zip
# стоп на ПК, потом:
systemctl start home24
EOS
```

Агент в облаке **не имеет** SSH/IP/.env продакшена — ZIP собирается локально/в артефактах, на сервер кладёте вы (или даёте доступ).
