/**
 * Timed from public/credits-song.mp3 (Whisper + energy).
 * After «ничего не осталось» (~23s) — silent lyric pause, then «а-а-о» ~29s.
 */
export const DURATION = 137.2;
export const AUDIO_SRC = '/credits-song.mp3';
export const LYRIC_LAG = 0.15;
export const HOLD_PAD = 0.25;

/**
 * t/end in seconds. Gap between end and next t = pause (text fades).
 */
export const CUES = [
  { t: 6.5, end: 10.5, text: 'KI-KI-KIDSCRY2DAY', mode: 'stamp' },

  // intro — протяжно
  { t: 11.88, end: 13.9, text: 'Злая шутка', mode: 'line' },
  { t: 14.48, end: 16.4, text: 'время ушло', mode: 'line' },
  { t: 16.98, end: 19.2, text: 'И после меня', mode: 'line' },
  { t: 19.06, end: 23.2, text: 'ничего не осталось', mode: 'impact' },
  // ★ пауза 23.2 → 29.1 — без текста

  // припев 1
  { t: 29.15, end: 30.05, text: 'а-а-о', mode: 'chorus' },
  { t: 30.15, end: 31.05, text: 'чё?', mode: 'glitch' },
  { t: 31.2, end: 32.9, text: 'а-а-о', mode: 'chorus' },
  { t: 32.1, end: 34.5, text: 'не осталось', mode: 'impact' },
  { t: 34.5, end: 36.8, text: 'а-а-о', mode: 'chorus' },
  { t: 36.9, end: 39.5, text: 'а-а-о', mode: 'chorus' },
  { t: 39.6, end: 42.5, text: 'а-а-о', mode: 'chorus' },
  // пауза до куплета

  // куплет 1 — плотнее
  { t: 44.9, end: 46.9, text: 'Не ждите меня дома', mode: 'line' },
  { t: 46.92, end: 48.8, text: 'утонул в празднике', mode: 'line' },
  { t: 48.98, end: 50.1, text: 'Мы такие разные', mode: 'line' },
  { t: 50.1, end: 52.3, text: 'хотя говорил иначе', mode: 'line' },
  { t: 52.48, end: 54.1, text: 'Из коробки бьёт фонтан', mode: 'line' },
  { t: 54.1, end: 56.1, text: 'В дешёвых отелях', mode: 'line' },
  { t: 56.1, end: 57.5, text: 'забыть чемодан', mode: 'line' },
  { t: 57.64, end: 58.7, text: 'Всё это кажется', mode: 'line' },
  { t: 58.7, end: 60.3, text: 'и ты просто бредишь', mode: 'line' },
  { t: 60.42, end: 61.8, text: 'Немного переживаю', mode: 'line' },
  { t: 61.8, end: 63.2, text: 'ща в ушах потемкин', mode: 'glitch' },
  { t: 63.38, end: 65.5, text: 'Прокрутить время стуком пробела', mode: 'line' },
  { t: 66.08, end: 67.7, text: 'Извини меня за это', mode: 'line' },
  { t: 68.06, end: 70.2, text: 'Стать старше, не вытирая сопли', mode: 'line' },
  { t: 70.34, end: 71.7, text: 'Музыка — тоска', mode: 'impact' },
  { t: 71.86, end: 73.3, text: 'пусть моменты будут фоном', mode: 'line' },
  { t: 73.34, end: 76.3, text: 'Смотри мне на руки, пока я тону', mode: 'impact' },
  { t: 76.5, end: 79.2, text: 'Рвётся спасательный круг', mode: 'impact' },
  // короткая пауза

  // припев 2
  { t: 79.5, end: 81.3, text: 'Ты как сам-то?', mode: 'line' },
  { t: 80.8, end: 82.4, text: 'ON-ON-ONDA', mode: 'stamp' },
  { t: 82.5, end: 84.2, text: 'а-а-о', mode: 'chorus' },
  { t: 84.42, end: 85.2, text: 'чё?', mode: 'glitch' },
  { t: 85.78, end: 87.2, text: 'Ты как сам-то?', mode: 'line' },
  { t: 86.9, end: 88.5, text: 'ONDA', mode: 'stamp' },
  { t: 87.5, end: 89.3, text: 'а-а-о', mode: 'chorus' },
  // пауза

  // куплет 2
  { t: 90.7, end: 92.2, text: 'Смеюсь как лиса', mode: 'line' },
  { t: 92.3, end: 93.5, text: 'они хотят меня', mode: 'line' },
  { t: 93.5, end: 95.0, text: 'Сверкают пятки', mode: 'line' },
  { t: 95.06, end: 96.55, text: 'до метро не добежал', mode: 'line' },
  { t: 96.54, end: 97.6, text: 'Чешется горло', mode: 'line' },
  { t: 97.68, end: 98.4, text: 'хочу кричать', mode: 'impact' },
  { t: 98.38, end: 99.1, text: 'но не могу', mode: 'line' },
  { t: 99.08, end: 100.8, text: 'Извини меня', mode: 'line' },
  { t: 101.04, end: 102.5, text: 'я не напишу', mode: 'impact' },
  { t: 102.3, end: 103.0, text: 'А чё так?', mode: 'glitch' },

  // финальный а-а-о — протяжнее
  { t: 103.0, end: 105.5, text: 'а-а-о', mode: 'chorus' },
  { t: 105.6, end: 108.0, text: 'а-а-о', mode: 'chorus' },
  { t: 108.1, end: 111.0, text: 'а-а-о', mode: 'chorus' },
  { t: 111.2, end: 114.5, text: 'а-а-о', mode: 'chorus' },
  { t: 115.0, end: 118.5, text: 'ON-ON-ONDA', mode: 'stamp' },
  { t: 122.0, end: 126.0, text: 'credits song', mode: 'stamp' },
  { t: 126.5, end: 130.5, text: 'ONDA ANDAR', mode: 'stamp' },
];

export const EVENTS = [
  { t: 0.0, scene: 'horizon' },
  { t: 6.5, scene: 'walk' },
  { t: 19.06, scene: 'void' },
  { t: 23.2, scene: 'horizon' }, // пауза после осталось
  { t: 29.15, scene: 'chorus-pulse' },
  { t: 44.9, scene: 'party' },
  { t: 46.92, scene: 'drown-party' },
  { t: 54.1, scene: 'hotel' },
  { t: 56.1, scene: 'suitcase' },
  { t: 63.38, scene: 'scrub' },
  { t: 70.34, scene: 'melancholy' },
  { t: 73.34, scene: 'hands' },
  { t: 75.46, scene: 'sink' },
  { t: 76.5, scene: 'lifebuoy' },
  { t: 80.8, scene: 'stamp-onda' },
  { t: 90.7, scene: 'fox' },
  { t: 93.5, scene: 'run' },
  { t: 97.68, scene: 'scream' },
  { t: 103.0, scene: 'chorus-pulse' },
  { t: 126.5, scene: 'end' },
];
