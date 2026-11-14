/**
 * Timed from real audio (SoundCloud → public/credits-song.mp3)
 * via Whisper word timestamps + energy peaks for chorus hooks.
 * Slow/drawn lines get long end windows; verse lines stay tight.
 */
export const DURATION = 137.2;
export const AUDIO_SRC = '/credits-song.mp3';
/** Tiny ear lag only — timeline is from the actual file. */
export const LYRIC_LAG = 0.12;
export const HOLD_PAD = 0.2;

/**
 * t/end in seconds. Between end and next t = pause (text soft-fades).
 * mode: line | chorus | impact | stamp | glitch
 */
export const CUES = [
  // beat cold open
  { t: 6.4, end: 10.8, text: 'KI-KI-KIDSCRY2DAY', mode: 'stamp' },

  // intro — протяжно
  { t: 11.16, end: 13.9, text: 'Злая шутка', mode: 'line' },
  { t: 14.48, end: 16.6, text: 'время ушло', mode: 'line' },
  { t: 17.0, end: 19.2, text: 'И после меня', mode: 'line' },
  { t: 19.2, end: 23.2, text: 'ничего не осталось', mode: 'impact' },
  // pause / build into chorus ~23.2–24.2

  // припев 1 — короткие хуки (energy 23–38)
  { t: 24.2, end: 25.8, text: 'а-а-о', mode: 'chorus' },
  { t: 25.9, end: 27.4, text: 'а-а-о', mode: 'chorus' },
  { t: 27.0, end: 28.0, text: 'чё?', mode: 'glitch' },
  { t: 28.1, end: 30.0, text: 'не осталось', mode: 'impact' },
  { t: 30.2, end: 32.5, text: 'а-а-о', mode: 'chorus' },
  { t: 32.6, end: 35.0, text: 'а-а-о', mode: 'chorus' },
  { t: 35.1, end: 37.8, text: 'а-а-о', mode: 'chorus' },
  // pause ~37.8–44.5

  // куплет 1 — плотнее / быстрее
  { t: 44.74, end: 46.9, text: 'Не ждите меня дома', mode: 'line' },
  { t: 46.96, end: 48.7, text: 'утонул в празднике', mode: 'line' },
  { t: 48.82, end: 50.0, text: 'Мы такие разные', mode: 'line' },
  { t: 50.06, end: 52.0, text: 'хотя говорил иначе', mode: 'line' },
  { t: 52.1, end: 54.0, text: 'Из коробки бьёт фонтан', mode: 'line' },
  { t: 54.1, end: 56.1, text: 'В дешёвых отелях', mode: 'line' },
  { t: 56.2, end: 57.45, text: 'забыть чемодан', mode: 'line' },
  { t: 57.5, end: 58.55, text: 'Всё это кажется', mode: 'line' },
  { t: 58.62, end: 60.2, text: 'и ты просто бредишь', mode: 'line' },
  { t: 60.42, end: 61.85, text: 'Немного переживаю', mode: 'line' },
  { t: 62.0, end: 63.3, text: 'ща в ушах потемкин', mode: 'glitch' },
  { t: 63.46, end: 65.7, text: 'Прокрутить время стуком пробела', mode: 'line' },
  { t: 66.14, end: 67.7, text: 'Извини меня за это', mode: 'line' },
  { t: 68.04, end: 70.35, text: 'Стать старше, не вытирая сопли', mode: 'line' },
  { t: 70.46, end: 71.75, text: 'Музыка — тоска', mode: 'impact' },
  { t: 71.84, end: 73.4, text: 'пусть моменты будут фоном', mode: 'line' },
  { t: 73.4, end: 76.4, text: 'Смотри мне на руки, пока я тону', mode: 'impact' },
  { t: 76.96, end: 79.3, text: 'Рвётся спасательный круг', mode: 'impact' },
  // pause ~79.3–79.9

  // припев 2
  { t: 79.96, end: 81.9, text: 'Ты как сам-то?', mode: 'line' },
  { t: 81.2, end: 82.4, text: 'ON-ON-ONDA', mode: 'stamp' },
  { t: 82.56, end: 84.2, text: 'а-а-о', mode: 'chorus' },
  { t: 83.9, end: 84.8, text: 'чё?', mode: 'glitch' },
  { t: 84.9, end: 86.5, text: 'Ты как сам-то?', mode: 'line' },
  { t: 86.5, end: 88.2, text: 'ONDA', mode: 'stamp' },
  { t: 87.3, end: 89.2, text: 'а-а-о', mode: 'chorus' },
  // pause ~89.2–90.4

  // куплет 2
  { t: 90.54, end: 92.2, text: 'Смеюсь как лиса', mode: 'line' },
  { t: 92.28, end: 93.55, text: 'они хотят меня', mode: 'line' },
  { t: 93.52, end: 95.5, text: 'Сверкают пятки', mode: 'line' },
  { t: 95.06, end: 96.55, text: 'до метро не добежал', mode: 'line' },
  { t: 96.52, end: 97.6, text: 'Чешется горло', mode: 'line' },
  { t: 97.7, end: 98.4, text: 'хочу кричать', mode: 'impact' },
  { t: 98.36, end: 99.15, text: 'но не могу', mode: 'line' },
  { t: 99.1, end: 101.0, text: 'Извини меня', mode: 'line' },
  { t: 101.04, end: 102.5, text: 'я не напишу', mode: 'impact' },
  { t: 102.4, end: 103.0, text: 'А чё так?', mode: 'glitch' },

  // финальный припев — протяжнее
  { t: 103.0, end: 105.4, text: 'а-а-о', mode: 'chorus' },
  { t: 105.6, end: 107.5, text: 'а-а-о', mode: 'chorus' },
  { t: 107.5, end: 110.5, text: 'а-а-о', mode: 'chorus' },
  { t: 110.5, end: 113.5, text: 'а-а-о', mode: 'chorus' },
  { t: 113.6, end: 116.5, text: 'ON-ON-ONDA', mode: 'stamp' },
  { t: 120.0, end: 124.0, text: 'credits song', mode: 'stamp' },
  { t: 124.5, end: 128.5, text: 'ONDA ANDAR', mode: 'stamp' },
];

export const EVENTS = [
  { t: 0.0, scene: 'horizon' },
  { t: 6.4, scene: 'walk' },
  { t: 19.2, scene: 'void' },
  { t: 24.2, scene: 'chorus-pulse' },
  { t: 44.74, scene: 'party' },
  { t: 46.96, scene: 'drown-party' },
  { t: 54.1, scene: 'hotel' },
  { t: 56.2, scene: 'suitcase' },
  { t: 63.46, scene: 'scrub' },
  { t: 70.46, scene: 'melancholy' },
  { t: 73.4, scene: 'hands' },
  { t: 75.46, scene: 'sink' },
  { t: 76.96, scene: 'lifebuoy' },
  { t: 81.2, scene: 'stamp-onda' },
  { t: 90.54, scene: 'fox' },
  { t: 93.52, scene: 'run' },
  { t: 97.7, scene: 'scream' },
  { t: 103.0, scene: 'chorus-pulse' },
  { t: 124.5, scene: 'end' },
];
