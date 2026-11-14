/** Lyrics synced to credits song (~2:17 / 168 BPM). Bar ≈ 1.429s. */
export const DURATION = 137;
export const YT_ID = 'e9l8AnnF0wU';

/**
 * t = когда показать, end = до когда держать на экране.
 * Между end и следующим t — пауза (текст гаснет).
 * mode: line | chorus | impact | stamp | glitch
 */
export const CUES = [
  // —— intro (bars ~4–14) ——
  { t: 5.7, end: 8.5, text: 'KI-KI-KIDSCRY2DAY', mode: 'stamp' },
  { t: 8.5, end: 11.4, text: 'Злая шутка', mode: 'line' },
  { t: 11.4, end: 14.3, text: 'время ушло', mode: 'line' },
  { t: 14.3, end: 17.1, text: 'И после меня', mode: 'line' },
  { t: 17.1, end: 21.0, text: 'ничего не осталось', mode: 'impact' },
  // pause ~21–25 (instrumental breath)

  // —— припев 1 (bars ~17–28), ~2 bars на хук ——
  { t: 25.0, end: 27.5, text: 'а-а-о', mode: 'chorus' },
  { t: 27.5, end: 29.5, text: 'а-а-о', mode: 'chorus' },
  { t: 28.8, end: 30.2, text: 'чё?', mode: 'glitch' },
  { t: 30.2, end: 32.8, text: 'не осталось', mode: 'impact' },
  { t: 32.8, end: 35.4, text: 'а-а-о', mode: 'chorus' },
  { t: 35.4, end: 38.0, text: 'а-а-о', mode: 'chorus' },
  // pause ~38–42

  // —— куплет 1 (bars ~29–64) ——
  { t: 42.0, end: 45.5, text: 'Не ждите меня дома', mode: 'line' },
  { t: 45.5, end: 49.0, text: 'утонул в празднике', mode: 'line' },
  { t: 49.0, end: 52.5, text: 'Мы такие разные', mode: 'line' },
  { t: 52.5, end: 56.0, text: 'хотя говорил иначе', mode: 'line' },
  { t: 56.0, end: 59.5, text: 'Из коробки бьёт фонтан', mode: 'line' },
  { t: 59.5, end: 63.0, text: 'В дешёвых отелях', mode: 'line' },
  { t: 63.0, end: 66.0, text: 'забыть чемодан', mode: 'line' },
  { t: 66.0, end: 69.5, text: 'Всё это кажется', mode: 'line' },
  { t: 69.5, end: 73.0, text: 'и ты просто бредишь', mode: 'line' },
  { t: 73.0, end: 76.5, text: 'ща в ушах потемкин', mode: 'glitch' },
  { t: 76.5, end: 80.0, text: 'Прокрутить время', mode: 'line' },
  { t: 80.0, end: 83.0, text: 'стуком пробела', mode: 'line' },
  { t: 83.0, end: 86.5, text: 'Извини меня за это', mode: 'line' },
  { t: 86.5, end: 89.5, text: 'Стать старше', mode: 'line' },
  { t: 89.5, end: 92.5, text: 'не вытирая сопли', mode: 'line' },
  { t: 92.5, end: 95.5, text: 'Музыка — тоска', mode: 'impact' },
  { t: 95.5, end: 99.0, text: 'пусть моменты будут фоном', mode: 'line' },
  { t: 99.0, end: 102.0, text: 'Смотри мне на руки', mode: 'line' },
  { t: 102.0, end: 105.0, text: 'пока я тону', mode: 'impact' },
  { t: 105.0, end: 108.5, text: 'Рвётся спасательный круг', mode: 'impact' },
  // pause ~108.5–112

  // —— припев 2 ——
  { t: 112.0, end: 114.0, text: 'Ты как сам-то?', mode: 'line' },
  { t: 114.0, end: 116.5, text: 'ON-ON-ONDA', mode: 'stamp' },
  { t: 116.5, end: 118.5, text: 'а-а-о', mode: 'chorus' },
  { t: 118.0, end: 119.2, text: 'чё?', mode: 'glitch' },
  { t: 119.2, end: 121.0, text: 'Ты как сам-то?', mode: 'line' },
  { t: 121.0, end: 123.0, text: 'ONDA', mode: 'stamp' },
  { t: 123.0, end: 125.0, text: 'а-а-о', mode: 'chorus' },
  // pause ~125–126.5

  // —— куплет 2 / outro ——
  { t: 126.5, end: 128.5, text: 'Смеюсь как лиса', mode: 'line' },
  { t: 128.5, end: 130.2, text: 'они хотят меня', mode: 'line' },
  { t: 130.2, end: 132.0, text: 'Сверкают пятки', mode: 'line' },
  { t: 132.0, end: 133.5, text: 'до метро не добежал', mode: 'line' },
  { t: 133.5, end: 134.6, text: 'хочу кричать', mode: 'impact' },
  { t: 134.6, end: 135.5, text: 'но не могу', mode: 'line' },
  { t: 135.5, end: 136.4, text: 'я не напишу', mode: 'impact' },
  { t: 136.4, end: 137.0, text: 'А чё так?', mode: 'glitch' },
];

/** Сюжетные события фона — на стыках секций / ключевых образах */
export const EVENTS = [
  { t: 0.0, scene: 'horizon' },
  { t: 5.7, scene: 'walk' },
  { t: 17.1, scene: 'void' },
  { t: 25.0, scene: 'chorus-pulse' },
  { t: 42.0, scene: 'party' },
  { t: 45.5, scene: 'drown-party' },
  { t: 59.5, scene: 'hotel' },
  { t: 63.0, scene: 'suitcase' },
  { t: 76.5, scene: 'scrub' },
  { t: 92.5, scene: 'melancholy' },
  { t: 99.0, scene: 'hands' },
  { t: 102.0, scene: 'sink' },
  { t: 105.0, scene: 'lifebuoy' },
  { t: 114.0, scene: 'stamp-onda' },
  { t: 126.5, scene: 'fox' },
  { t: 130.2, scene: 'run' },
  { t: 133.5, scene: 'scream' },
  { t: 136.4, scene: 'end' },
];
