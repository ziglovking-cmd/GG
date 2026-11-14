/**
 * Timed from real audio (SoundCloud → public/credits-song.mp3)
 * via Whisper word timestamps + energy peaks for chorus hooks.
 * Slow/drawn lines get long end windows; verse lines stay tight.
 */
export const DURATION = 137.2;
export const AUDIO_SRC = '/credits-song.mp3';
/**
 * Whisper word starts run early vs perceived vocal — hold text back.
 * Tune this if it still leads/lags.
 */
export const LYRIC_LAG = 1.55;
export const HOLD_PAD = 0.45;

/**
 * t/end in seconds. Between end and next t = pause (text soft-fades).
 * mode: line | chorus | impact | stamp | glitch
 */
export const CUES = [
  // beat cold open
  { t: 6.75, end: 11.15, text: 'KI-KI-KIDSCRY2DAY', mode: 'stamp' },

  // intro — протяжно
  { t: 11.51, end: 14.25, text: 'Злая шутка', mode: 'line' },
  { t: 14.83, end: 16.95, text: 'время ушло', mode: 'line' },
  { t: 17.35, end: 19.55, text: 'И после меня', mode: 'line' },
  { t: 19.55, end: 23.55, text: 'ничего не осталось', mode: 'impact' },
  // pause / build into chorus ~23.2–24.2

  // припев 1 — короткие хуки (energy 23–38)
  { t: 24.55, end: 26.15, text: 'а-а-о', mode: 'chorus' },
  { t: 26.25, end: 27.75, text: 'а-а-о', mode: 'chorus' },
  { t: 27.35, end: 28.35, text: 'чё?', mode: 'glitch' },
  { t: 28.45, end: 30.35, text: 'не осталось', mode: 'impact' },
  { t: 30.55, end: 32.85, text: 'а-а-о', mode: 'chorus' },
  { t: 32.95, end: 35.35, text: 'а-а-о', mode: 'chorus' },
  { t: 35.45, end: 38.15, text: 'а-а-о', mode: 'chorus' },
  // pause ~37.8–44.5

  // куплет 1 — плотнее / быстрее
  { t: 45.09, end: 47.25, text: 'Не ждите меня дома', mode: 'line' },
  { t: 47.31, end: 49.05, text: 'утонул в празднике', mode: 'line' },
  { t: 49.17, end: 50.35, text: 'Мы такие разные', mode: 'line' },
  { t: 50.41, end: 52.35, text: 'хотя говорил иначе', mode: 'line' },
  { t: 52.45, end: 54.35, text: 'Из коробки бьёт фонтан', mode: 'line' },
  { t: 54.45, end: 56.45, text: 'В дешёвых отелях', mode: 'line' },
  { t: 56.55, end: 57.80, text: 'забыть чемодан', mode: 'line' },
  { t: 57.85, end: 58.90, text: 'Всё это кажется', mode: 'line' },
  { t: 58.97, end: 60.55, text: 'и ты просто бредишь', mode: 'line' },
  { t: 60.77, end: 62.20, text: 'Немного переживаю', mode: 'line' },
  { t: 62.35, end: 63.65, text: 'ща в ушах потемкин', mode: 'glitch' },
  { t: 63.81, end: 66.05, text: 'Прокрутить время стуком пробела', mode: 'line' },
  { t: 66.49, end: 68.05, text: 'Извини меня за это', mode: 'line' },
  { t: 68.39, end: 70.70, text: 'Стать старше, не вытирая сопли', mode: 'line' },
  { t: 70.81, end: 72.10, text: 'Музыка — тоска', mode: 'impact' },
  { t: 72.19, end: 73.75, text: 'пусть моменты будут фоном', mode: 'line' },
  { t: 73.75, end: 76.75, text: 'Смотри мне на руки, пока я тону', mode: 'impact' },
  { t: 77.31, end: 79.65, text: 'Рвётся спасательный круг', mode: 'impact' },
  // pause ~79.3–79.9

  // припев 2
  { t: 80.31, end: 82.25, text: 'Ты как сам-то?', mode: 'line' },
  { t: 81.55, end: 82.75, text: 'ON-ON-ONDA', mode: 'stamp' },
  { t: 82.91, end: 84.55, text: 'а-а-о', mode: 'chorus' },
  { t: 84.25, end: 85.15, text: 'чё?', mode: 'glitch' },
  { t: 85.25, end: 86.85, text: 'Ты как сам-то?', mode: 'line' },
  { t: 86.85, end: 88.55, text: 'ONDA', mode: 'stamp' },
  { t: 87.65, end: 89.55, text: 'а-а-о', mode: 'chorus' },
  // pause ~89.2–90.4

  // куплет 2
  { t: 90.89, end: 92.55, text: 'Смеюсь как лиса', mode: 'line' },
  { t: 92.63, end: 93.90, text: 'они хотят меня', mode: 'line' },
  { t: 93.87, end: 95.85, text: 'Сверкают пятки', mode: 'line' },
  { t: 95.41, end: 96.90, text: 'до метро не добежал', mode: 'line' },
  { t: 96.87, end: 97.95, text: 'Чешется горло', mode: 'line' },
  { t: 98.05, end: 98.75, text: 'хочу кричать', mode: 'impact' },
  { t: 98.71, end: 99.50, text: 'но не могу', mode: 'line' },
  { t: 99.45, end: 101.35, text: 'Извини меня', mode: 'line' },
  { t: 101.39, end: 102.85, text: 'я не напишу', mode: 'impact' },
  { t: 102.75, end: 103.35, text: 'А чё так?', mode: 'glitch' },

  // финальный припев — протяжнее
  { t: 103.35, end: 105.75, text: 'а-а-о', mode: 'chorus' },
  { t: 105.95, end: 107.85, text: 'а-а-о', mode: 'chorus' },
  { t: 107.85, end: 110.85, text: 'а-а-о', mode: 'chorus' },
  { t: 110.85, end: 113.85, text: 'а-а-о', mode: 'chorus' },
  { t: 113.95, end: 116.85, text: 'ON-ON-ONDA', mode: 'stamp' },
  { t: 120.35, end: 124.35, text: 'credits song', mode: 'stamp' },
  { t: 124.85, end: 128.85, text: 'ONDA ANDAR', mode: 'stamp' },
];

export const EVENTS = [
  { t: 0.35, scene: 'horizon' },
  { t: 6.75, scene: 'walk' },
  { t: 19.55, scene: 'void' },
  { t: 24.55, scene: 'chorus-pulse' },
  { t: 45.09, scene: 'party' },
  { t: 47.31, scene: 'drown-party' },
  { t: 54.45, scene: 'hotel' },
  { t: 56.55, scene: 'suitcase' },
  { t: 63.81, scene: 'scrub' },
  { t: 70.81, scene: 'melancholy' },
  { t: 73.75, scene: 'hands' },
  { t: 75.81, scene: 'sink' },
  { t: 77.31, scene: 'lifebuoy' },
  { t: 81.55, scene: 'stamp-onda' },
  { t: 90.89, scene: 'fox' },
  { t: 93.87, scene: 'run' },
  { t: 98.05, scene: 'scream' },
  { t: 103.35, scene: 'chorus-pulse' },
  { t: 124.85, scene: 'end' },
];
