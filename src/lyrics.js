/**
 * Forced-aligned to public/credits-song.mp3 (stable-ts + vocal-band).
 * Phrase holds are stretched so lines breathe with the vocal;
 * empty window after «ничего не осталось» before «а-а-о».
 */
export const DURATION = 137.2;
export const AUDIO_SRC = '/credits-song.mp3';
/**
 * Small cushion on top of AudioContext outputLatency so HUD sits on the
 * heard vocal. Clock is performance.now (true 1×); do not use a large lag
 * or lines trail the voice.
 */
export const LYRIC_LAG = 0.28;

/**
 * Inclusive window: visible while lagTime ∈ [t, end).
 * Real gap with no cue = pause (HUD soft-clears).
 */
export const CUES = [
  { t: 9.83, end: 11.35, text: 'KI-KI-KIDSCRY2DAY', mode: 'stamp' },

  // intro — протяжно, each line held past the sung tail
  { t: 11.35, end: 14.2, text: 'Злая шутка', mode: 'line' },
  { t: 14.2, end: 17.0, text: 'время ушло', mode: 'line' },
  { t: 17.0, end: 19.5, text: 'И после меня', mode: 'line' },
  // drawn-out landing; whisper puts «осталось» ~21–23, then instrumental bed
  { t: 19.5, end: 24.2, text: 'ничего не осталось', mode: 'impact' },
  // PAUSE 24.2 → 28.9 — beat continues, text clears before chorus

  // припев 1 — vocal-band rise ~28.6, first «а-а-о» ~28.8
  { t: 28.9, end: 30.15, text: 'а-а-о', mode: 'chorus' },
  { t: 30.15, end: 31.0, text: 'чё?', mode: 'glitch' },
  { t: 31.0, end: 32.5, text: 'а-а-о', mode: 'chorus' },
  { t: 32.5, end: 35.0, text: 'не осталось', mode: 'impact' },
  { t: 35.0, end: 38.2, text: 'а-а-о', mode: 'chorus' },
  { t: 40.16, end: 41.7, text: 'а-а-о', mode: 'chorus' },
  { t: 41.7, end: 44.5, text: 'а-а-о', mode: 'chorus' },

  // куплет 1
  { t: 44.5, end: 47.0, text: 'Не ждите меня дома', mode: 'line' },
  { t: 47.0, end: 49.0, text: 'утонул в празднике', mode: 'line' },
  { t: 49.0, end: 50.3, text: 'Мы такие разные', mode: 'line' },
  { t: 50.3, end: 52.4, text: 'хотя говорил иначе', mode: 'line' },
  { t: 52.4, end: 54.4, text: 'Из коробки бьёт фонтан', mode: 'line' },
  { t: 54.4, end: 56.4, text: 'В дешёвых отелях', mode: 'line' },
  { t: 56.4, end: 57.7, text: 'забыть чемодан', mode: 'line' },
  { t: 57.7, end: 58.8, text: 'Всё это кажется', mode: 'line' },
  { t: 58.8, end: 60.5, text: 'и ты просто бредишь', mode: 'line' },
  { t: 60.5, end: 61.9, text: 'Немного переживаю', mode: 'line' },
  { t: 61.9, end: 63.5, text: 'ща в ушах потемкин', mode: 'glitch' },
  { t: 63.5, end: 65.9, text: 'Прокрутить время стуком пробела', mode: 'line' },
  { t: 65.9, end: 67.9, text: 'Извини меня за это', mode: 'line' },
  { t: 67.9, end: 70.8, text: 'Стать старше, не вытирая сопли', mode: 'line' },
  { t: 70.8, end: 72.0, text: 'Музыка — тоска', mode: 'impact' },
  { t: 72.0, end: 73.5, text: 'пусть моменты будут фоном', mode: 'line' },
  { t: 73.5, end: 76.6, text: 'Смотри мне на руки, пока я тону', mode: 'impact' },
  { t: 76.6, end: 79.4, text: 'Рвётся спасательный круг', mode: 'impact' },

  // припев 2
  { t: 79.4, end: 81.3, text: 'Ты как сам-то?', mode: 'line' },
  { t: 81.3, end: 82.2, text: 'ON-ON-ONDA', mode: 'stamp' },
  { t: 82.2, end: 83.7, text: 'а-а-о', mode: 'chorus' },
  { t: 83.7, end: 85.5, text: 'чё?', mode: 'glitch' },
  { t: 85.5, end: 86.8, text: 'Ты как сам-то?', mode: 'line' },
  { t: 86.8, end: 88.2, text: 'ONDA', mode: 'stamp' },
  { t: 88.2, end: 89.5, text: 'а-а-о', mode: 'chorus' },

  // куплет 2
  { t: 89.5, end: 92.2, text: 'Смеюсь как лиса', mode: 'line' },
  { t: 92.2, end: 93.7, text: 'они хотят меня', mode: 'line' },
  { t: 93.7, end: 95.2, text: 'Сверкают пятки', mode: 'line' },
  { t: 95.2, end: 96.7, text: 'до метро не добежал', mode: 'line' },
  { t: 96.7, end: 97.7, text: 'Чешется горло', mode: 'line' },
  { t: 97.7, end: 98.5, text: 'хочу кричать', mode: 'impact' },
  { t: 98.5, end: 99.3, text: 'но не могу', mode: 'line' },
  { t: 99.3, end: 101.0, text: 'Извини меня', mode: 'line' },
  { t: 101.0, end: 102.5, text: 'я не напишу', mode: 'impact' },
  { t: 102.5, end: 103.0, text: 'А чё так?', mode: 'glitch' },

  // финал — протяжнее
  { t: 103.0, end: 105.0, text: 'а-а-о', mode: 'chorus' },
  { t: 105.0, end: 108.0, text: 'а-а-о', mode: 'chorus' },
  { t: 108.0, end: 112.0, text: 'а-а-о', mode: 'chorus' },
  { t: 112.0, end: 116.0, text: 'ON-ON-ONDA', mode: 'stamp' },
  { t: 120.0, end: 125.0, text: 'credits song', mode: 'stamp' },
  { t: 125.5, end: 131.0, text: 'ONDA ANDAR', mode: 'stamp' },
];

export const EVENTS = [
  { t: 0.0, scene: 'horizon' },
  { t: 9.83, scene: 'walk' },
  { t: 19.5, scene: 'void' },
  { t: 24.2, scene: 'horizon' },
  { t: 28.9, scene: 'chorus-pulse' },
  // куплет 1 — сюжетные декорации
  { t: 44.5, scene: 'home' }, // Не ждите меня дома
  { t: 47.0, scene: 'drown-party' }, // утонул в празднике
  { t: 49.0, scene: 'party' },
  { t: 52.4, scene: 'fountain' }, // Из коробки бьёт фонтан
  { t: 54.4, scene: 'hotel' }, // В дешёвых отелях
  { t: 56.4, scene: 'suitcase' }, // забыть чемодан
  { t: 58.8, scene: 'delirium' }, // ты просто бредишь
  { t: 61.9, scene: 'potyomkin' }, // ща в ушах потемкин
  { t: 63.5, scene: 'scrub' }, // стуком пробела
  { t: 70.8, scene: 'melancholy' },
  { t: 73.5, scene: 'hands' }, // Смотри мне на руки
  { t: 75.5, scene: 'sink' },
  { t: 76.6, scene: 'lifebuoy' }, // Рвётся спасательный круг
  { t: 81.3, scene: 'stamp-onda' },
  // куплет 2
  { t: 89.5, scene: 'fox' }, // Смеюсь как лиса — FP обочина
  { t: 92.2, scene: 'chase' }, // они хотят меня
  { t: 93.7, scene: 'run' }, // Сверкают пятки
  { t: 95.2, scene: 'metro' }, // до метро не добежал
  { t: 97.7, scene: 'scream' }, // хочу кричать
  { t: 99.3, scene: 'apology' },
  { t: 103.0, scene: 'chorus-pulse' },
  { t: 125.5, scene: 'end' },
];
