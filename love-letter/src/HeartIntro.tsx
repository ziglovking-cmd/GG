import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { site } from './config'

type Piece = {
  id: number
  startX: number
  startY: number
  targetX: number
  targetY: number
  size: number
  rotate: number
  delay: number
  hue: number
}

type Phase = 'playing' | 'complete' | 'leaving'

/** Relative slots that form a heart silhouette (percent of stage) */
const HEART_SLOTS: Array<[number, number]> = [
  [50, 28],
  [38, 22],
  [62, 22],
  [28, 32],
  [72, 32],
  [34, 44],
  [66, 44],
  [42, 56],
  [58, 56],
  [50, 68],
  [44, 40],
  [56, 40],
]

const HINTS = [
  'тапни все огоньки — соберём сердечко',
  'ещё чуть-чуть, ты справишься',
  'почти… оно уже бьётся',
  'осталось совсем капелька',
]

function scatterAround(index: number, total: number): [number, number] {
  const ring = index % 2 === 0 ? 1 : 0
  const angle = (index / total) * Math.PI * 2 + (ring ? 0.4 : 0)
  const radius = ring === 0 ? 34 : 42
  const cx = 50 + Math.cos(angle) * radius
  const cy = 48 + Math.sin(angle) * (radius * 0.72)
  return [
    Math.min(92, Math.max(8, cx + ((index * 7) % 9) - 4)),
    Math.min(88, Math.max(12, cy + ((index * 5) % 11) - 5)),
  ]
}

type HeartIntroProps = {
  onDone: () => void
}

export function HeartIntro({ onDone }: HeartIntroProps) {
  const pieces = useMemo<Piece[]>(
    () =>
      HEART_SLOTS.map(([tx, ty], index) => {
        const [sx, sy] = scatterAround(index, HEART_SLOTS.length)
        return {
          id: index,
          startX: sx,
          startY: sy,
          targetX: tx,
          targetY: ty,
          size: 18 + (index % 4) * 4,
          rotate: -28 + ((index * 17) % 56),
          delay: index * 0.06,
          hue: index % 3,
        }
      }),
    [],
  )

  const [collected, setCollected] = useState<Set<number>>(() => new Set())
  const [phase, setPhase] = useState<Phase>('playing')
  const [entered, setEntered] = useState(false)

  useEffect(() => {
    const id = window.requestAnimationFrame(() => setEntered(true))
    return () => window.cancelAnimationFrame(id)
  }, [])

  useEffect(() => {
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = ''
    }
  }, [])

  useEffect(() => {
    if (collected.size !== pieces.length || phase !== 'playing') return
    setPhase('complete')
    const leave = window.setTimeout(() => setPhase('leaving'), 1600)
    const done = window.setTimeout(() => onDone(), 2400)
    return () => {
      window.clearTimeout(leave)
      window.clearTimeout(done)
    }
  }, [collected, pieces.length, phase, onDone])

  function collect(id: number) {
    if (phase !== 'playing') return
    setCollected((prev) => {
      if (prev.has(id)) return prev
      const next = new Set(prev)
      next.add(id)
      return next
    })
  }

  const progress = collected.size / pieces.length
  const hintIndex = Math.min(HINTS.length - 1, Math.floor(progress * HINTS.length))

  return (
    <div
      className={`intro ${entered ? 'intro--in' : ''} ${phase === 'leaving' ? 'intro--out' : ''} ${phase !== 'playing' ? 'intro--done' : ''}`}
      role="dialog"
      aria-modal="true"
      aria-label="Собери сердечко"
    >
      <div className="intro__glow" aria-hidden="true" />
      <div className="intro__dust" aria-hidden="true">
        {Array.from({ length: 18 }, (_, i) => (
          <span
            key={i}
            className="intro__dot"
            style={{
              left: `${(i * 17 + 9) % 100}%`,
              top: `${(i * 23 + 11) % 100}%`,
              animationDelay: `${i * 0.35}s`,
            }}
          />
        ))}
      </div>

      <div className="intro__top">
        <p className="intro__eyebrow">мини-квест · 12 кусочков</p>
        <h2 className="intro__title">
          {phase === 'playing' ? `собери сердечко для ${site.herName}` : 'готово. оно твоё'}
        </h2>
        <p className="intro__hint">
          {phase === 'playing' ? HINTS[hintIndex] : 'сейчас откроется кое-что милое…'}
        </p>
      </div>

      <div className="intro__stage">
        <div
          className={`intro__ghost ${collected.size > 0 ? 'intro__ghost--soft' : ''}`}
          aria-hidden="true"
        >
          <svg viewBox="0 0 24 24">
            <path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z" />
          </svg>
        </div>

        {pieces.map((piece) => {
          const isIn = collected.has(piece.id)
          return (
            <button
              key={piece.id}
              type="button"
              className={`intro__piece hue-${piece.hue} ${isIn ? 'is-home' : 'is-loose'} ${phase !== 'playing' ? 'is-locked' : ''}`}
              style={
                {
                  left: `${isIn ? piece.targetX : piece.startX}%`,
                  top: `${isIn ? piece.targetY : piece.startY}%`,
                  width: piece.size,
                  height: piece.size,
                  '--rot': `${isIn ? 0 : piece.rotate}deg`,
                  animationDelay: `${piece.delay}s`,
                } as CSSProperties
              }
              onClick={() => collect(piece.id)}
              aria-label={isIn ? 'Уже на месте' : 'Взять кусочек сердца'}
              disabled={isIn || phase !== 'playing'}
            >
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path
                  fill="currentColor"
                  d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"
                />
              </svg>
            </button>
          )
        })}

        <div
          className={`intro__assembled ${phase !== 'playing' ? 'is-visible' : ''}`}
          aria-hidden="true"
        >
          <svg viewBox="0 0 24 24">
            <path
              fill="currentColor"
              d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"
            />
          </svg>
        </div>
      </div>

      <div className="intro__progress" aria-live="polite">
        <div className="intro__bar">
          <span style={{ width: `${progress * 100}%` }} />
        </div>
        <p className="intro__count">
          {collected.size} / {pieces.length}
        </p>
      </div>
    </div>
  )
}
