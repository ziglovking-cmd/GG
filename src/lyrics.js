/** Timed lyrics + scene events for credits song (~2:17). Synced to YT playback. */
export const DURATION = 137;
export const YT_ID = 'e9l8AnnF0wU';

/**
 * mode: line | chorus | impact | stamp | glitch | pause
 * pause = слова гаснут, сцена дышит
 */
export const CUES = [
  // intro
  { t: 3.0, text: 'KI-KI-KIDSCRY2DAY', mode: 'stamp' },
  { t: 7.0, text: 'Злая шутка', mode: 'line' },
  { t: 10.5, text: 'время ушло', mode: 'line' },
  { t: 14.0, text: 'И после меня', mode: 'line' },
  { t: 17.5, text: 'ничего не осталось', mode: 'impact' },
  { t: 20.5, text: '', mode: 'pause' },

  // припев 1
  { t: 22.5, text: 'а-а-о', mode: 'chorus' },
  { t: 25.0, text: 'а-а-о', mode: 'chorus' },
  { t: 27.2, text: 'чё?', mode: 'glitch' },
  { t: 29.0, text: 'не осталось', mode: 'impact' },
  { t: 31.5, text: 'а-а-о', mode: 'chorus' },
  { t: 34.0, text: 'а-а-о', mode: 'chorus' },
  { t: 36.5, text: '', mode: 'pause' },

  // куплет 1
  { t: 38.5, text: 'Не ждите меня дома', mode: 'line' },
  { t: 42.0, text: 'утонул в празднике', mode: 'line' },
  { t: 45.5, text: 'Мы такие разные', mode: 'line' },
  { t: 48.8, text: 'хотя говорил иначе', mode: 'line' },
  { t: 52.0, text: '', mode: 'pause' },
  { t: 53.5, text: 'Из коробки бьёт фонтан', mode: 'line' },
  { t: 57.0, text: 'В дешёвых отелях', mode: 'line' },
  { t: 59.8, text: 'забыть чемодан', mode: 'line' },
  { t: 62.5, text: '', mode: 'pause' },
  { t: 64.0, text: 'Всё это кажется', mode: 'line' },
  { t: 67.0, text: 'и ты просто бредишь', mode: 'line' },
  { t: 70.0, text: 'ща в ушах потемкин', mode: 'glitch' },
  { t: 73.0, text: 'Прокрутить время', mode: 'line' },
  { t: 75.5, text: 'стуком пробела', mode: 'line' },
  { t: 78.5, text: 'Извини меня за это', mode: 'line' },
  { t: 81.5, text: '', mode: 'pause' },
  { t: 83.0, text: 'Стать старше', mode: 'line' },
  { t: 85.5, text: 'не вытирая сопли', mode: 'line' },
  { t: 88.5, text: 'Музыка — тоска', mode: 'impact' },
  { t: 91.5, text: 'пусть моменты будут фоном', mode: 'line' },
  { t: 94.5, text: '', mode: 'pause' },
  { t: 96.0, text: 'Смотри мне на руки', mode: 'line' },
  { t: 98.8, text: 'пока я тону', mode: 'impact' },
  { t: 101.5, text: 'Рвётся спасательный круг', mode: 'impact' },
  { t: 104.5, text: '', mode: 'pause' },

  // припев 2
  { t: 106.0, text: 'Ты как сам-то?', mode: 'line' },
  { t: 108.5, text: 'ON-ON-ONDA', mode: 'stamp' },
  { t: 111.0, text: 'а-а-о', mode: 'chorus' },
  { t: 113.0, text: 'чё?', mode: 'glitch' },
  { t: 114.8, text: 'Ты как сам-то?', mode: 'line' },
  { t: 117.0, text: 'ONDA', mode: 'stamp' },
  { t: 119.0, text: 'а-а-о', mode: 'chorus' },
  { t: 121.0, text: '', mode: 'pause' },

  // куплет 2 + хвост
  { t: 122.0, text: 'Смеюсь как лиса', mode: 'line' },
  { t: 124.5, text: 'они хотят меня', mode: 'line' },
  { t: 127.0, text: 'Сверкают пятки', mode: 'line' },
  { t: 129.2, text: 'до метро не добежал', mode: 'line' },
  { t: 131.5, text: 'хочу кричать', mode: 'impact' },
  { t: 133.2, text: 'но не могу', mode: 'line' },
  { t: 134.6, text: 'я не напишу', mode: 'impact' },
  { t: 136.0, text: 'А чё так?', mode: 'glitch' },
];

/** Сюжетные события фона */
export const EVENTS = [
  { t: 0.0, scene: 'horizon' },
  { t: 3.0, scene: 'walk' },
  { t: 17.5, scene: 'void' },
  { t: 22.5, scene: 'chorus-pulse' },
  { t: 38.5, scene: 'party' },
  { t: 42.0, scene: 'drown-party' },
  { t: 57.0, scene: 'hotel' },
  { t: 59.8, scene: 'suitcase' },
  { t: 73.0, scene: 'scrub' },
  { t: 88.5, scene: 'melancholy' },
  { t: 96.0, scene: 'hands' },
  { t: 98.8, scene: 'sink' },
  { t: 101.5, scene: 'lifebuoy' },
  { t: 108.5, scene: 'stamp-onda' },
  { t: 122.0, scene: 'fox' },
  { t: 127.0, scene: 'run' },
  { t: 131.5, scene: 'scream' },
  { t: 136.0, scene: 'end' },
];
