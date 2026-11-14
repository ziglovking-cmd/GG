/**
 * Forced-aligned to public/credits-song.mp3 (stable-ts) + manual pause
 * after «ничего не осталось» before «а-а-о» (per track listen).
 */
export const DURATION = 137.2;
export const AUDIO_SRC = '/credits-song.mp3';
/** Delay so on-screen lines sit on the vocal, not ahead of it. */
export const LYRIC_LAG = 0.85;

/**
 * Inclusive window: visible while lagTime ∈ [t, end).
 * Real gap with no cue = pause (HUD soft-clears).
 */
export const CUES = [
  { t: 9.93, end: 11.28, text: 'KI-KI-KIDSCRY2DAY', mode: 'stamp' },

  // intro — протяжно
  { t: 11.28, end: 13.64, text: 'Злая шутка', mode: 'line' },
  { t: 13.64, end: 16.16, text: 'время ушло', mode: 'line' },
  { t: 16.16, end: 19.06, text: 'И после меня', mode: 'line' },
  // held to the end of the sung phrase, then empty pause before chorus
  { t: 19.2, end: 23.6, text: 'ничего не осталось', mode: 'impact' },
  // PAUSE 23.6 → 29.0 (no cues) — beat continues, text stays clear

  // припев 1
  { t: 29.0, end: 30.1, text: 'а-а-о', mode: 'chorus' },
  { t: 30.12, end: 30.9, text: 'чё?', mode: 'glitch' },
  { t: 30.9, end: 32.5, text: 'а-а-о', mode: 'chorus' },
  { t: 32.34, end: 34.5, text: 'не осталось', mode: 'impact' },
  { t: 34.5, end: 37.5, text: 'а-а-о', mode: 'chorus' },
  { t: 40.16, end: 41.5, text: 'а-а-о', mode: 'chorus' },
  { t: 42.01, end: 43.8, text: 'а-а-о', mode: 'chorus' },
  // pause → verse

  // куплет 1
  { t: 43.9, end: 46.9, text: 'Не ждите меня дома', mode: 'line' },
  { t: 46.9, end: 48.84, text: 'утонул в празднике', mode: 'line' },
  { t: 48.84, end: 50.1, text: 'Мы такие разные', mode: 'line' },
  { t: 50.1, end: 52.1, text: 'хотя говорил иначе', mode: 'line' },
  { t: 52.1, end: 54.32, text: 'Из коробки бьёт фонтан', mode: 'line' },
  { t: 54.32, end: 56.18, text: 'В дешёвых отелях', mode: 'line' },
  { t: 56.18, end: 57.48, text: 'забыть чемодан', mode: 'line' },
  { t: 57.48, end: 58.6, text: 'Всё это кажется', mode: 'line' },
  { t: 58.6, end: 60.3, text: 'и ты просто бредишь', mode: 'line' },
  { t: 60.3, end: 61.72, text: 'Немного переживаю', mode: 'line' },
  { t: 61.72, end: 63.26, text: 'ща в ушах потемкин', mode: 'glitch' },
  { t: 63.26, end: 65.64, text: 'Прокрутить время стуком пробела', mode: 'line' },
  { t: 65.64, end: 67.64, text: 'Извини меня за это', mode: 'line' },
  { t: 67.64, end: 70.54, text: 'Стать старше, не вытирая сопли', mode: 'line' },
  { t: 70.54, end: 71.74, text: 'Музыка — тоска', mode: 'impact' },
  { t: 71.74, end: 73.26, text: 'пусть моменты будут фоном', mode: 'line' },
  { t: 73.26, end: 76.42, text: 'Смотри мне на руки, пока я тону', mode: 'impact' },
  { t: 76.42, end: 79.22, text: 'Рвётся спасательный круг', mode: 'impact' },

  // припев 2
  { t: 79.22, end: 81.2, text: 'Ты как сам-то?', mode: 'line' },
  { t: 81.2, end: 82.4, text: 'ON-ON-ONDA', mode: 'stamp' },
  { t: 81.94, end: 83.5, text: 'а-а-о', mode: 'chorus' },
  { t: 83.48, end: 85.3, text: 'чё?', mode: 'glitch' },
  { t: 85.36, end: 86.7, text: 'Ты как сам-то?', mode: 'line' },
  { t: 86.62, end: 87.8, text: 'ONDA', mode: 'stamp' },
  { t: 88.06, end: 89.5, text: 'а-а-о', mode: 'chorus' },

  // куплет 2
  { t: 89.5, end: 91.7, text: 'Смеюсь как лиса', mode: 'line' },
  { t: 92.06, end: 93.52, text: 'они хотят меня', mode: 'line' },
  { t: 93.52, end: 95.0, text: 'Сверкают пятки', mode: 'line' },
  { t: 95.06, end: 96.52, text: 'до метро не добежал', mode: 'line' },
  { t: 96.52, end: 97.54, text: 'Чешется горло', mode: 'line' },
  { t: 97.54, end: 98.34, text: 'хочу кричать', mode: 'impact' },
  { t: 98.34, end: 99.12, text: 'но не могу', mode: 'line' },
  { t: 99.12, end: 100.8, text: 'Извини меня', mode: 'line' },
  { t: 100.76, end: 102.3, text: 'я не напишу', mode: 'impact' },
  { t: 102.24, end: 102.9, text: 'А чё так?', mode: 'glitch' },

  // финал — протяжнее
  { t: 102.9, end: 105.5, text: 'а-а-о', mode: 'chorus' },
  { t: 105.5, end: 107.5, text: 'а-а-о', mode: 'chorus' },
  { t: 107.5, end: 110.5, text: 'а-а-о', mode: 'chorus' },
  { t: 112.0, end: 116.0, text: 'ON-ON-ONDA', mode: 'stamp' },
  { t: 120.0, end: 125.0, text: 'credits song', mode: 'stamp' },
  { t: 125.5, end: 131.0, text: 'ONDA ANDAR', mode: 'stamp' },
];

export const EVENTS = [
  { t: 0.0, scene: 'horizon' },
  { t: 9.93, scene: 'walk' },
  { t: 19.06, scene: 'void' },
  { t: 24.0, scene: 'horizon' },
  { t: 29.0, scene: 'chorus-pulse' },
  { t: 43.9, scene: 'party' },
  { t: 46.9, scene: 'drown-party' },
  { t: 54.32, scene: 'hotel' },
  { t: 56.18, scene: 'suitcase' },
  { t: 63.26, scene: 'scrub' },
  { t: 70.54, scene: 'melancholy' },
  { t: 73.26, scene: 'hands' },
  { t: 75.44, scene: 'sink' },
  { t: 76.42, scene: 'lifebuoy' },
  { t: 81.2, scene: 'stamp-onda' },
  { t: 89.5, scene: 'fox' },
  { t: 93.52, scene: 'run' },
  { t: 97.54, scene: 'scream' },
  { t: 102.9, scene: 'chorus-pulse' },
  { t: 125.5, scene: 'end' },
];
