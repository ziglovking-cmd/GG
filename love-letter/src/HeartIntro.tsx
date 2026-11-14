import { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { site } from './config'

type Phase = 'boot' | 'shatter' | 'collect' | 'assemble' | 'reveal' | 'leaving'

type Shard = {
  id: number
  angle: number
  radius: number
  homeX: number
  homeY: number
  size: number
  spin: number
}

/** Heart mosaic home slots, percent of stage */
const HOME: Array<[number, number]> = [
  [50, 28],
  [36, 22],
  [64, 22],
  [26, 36],
  [74, 36],
  [32, 52],
  [68, 52],
  [42, 66],
  [58, 66],
  [50, 78],
]

function makeShards(): Shard[] {
  return HOME.map(([hx, hy], id) => {
    const angle = -Math.PI / 2 + (id / HOME.length) * Math.PI * 2
    return {
      id,
      angle,
      radius: 38 + (id % 3) * 4,
      homeX: hx,
      homeY: hy,
      size: 56 + (id % 3) * 6,
      spin: -25 + ((id * 23) % 50),
    }
  })
}

type HeartIntroProps = {
  onDone: () => void
}

export function HeartIntro({ onDone }: HeartIntroProps) {
  const shards = useMemo(() => makeShards(), [])
  const [phase, setPhase] = useState<Phase>('boot')
  const [collected, setCollected] = useState<Set<number>>(() => new Set())
  const [activeId, setActiveId] = useState(0)
  const doneRef = useRef(onDone)
  doneRef.current = onDone

  useEffect(() => {
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = ''
    }
  }, [])

  useEffect(() => {
    const t1 = window.setTimeout(() => setPhase('shatter'), 800)
    const t2 = window.setTimeout(() => setPhase('collect'), 2000)
    return () => {
      window.clearTimeout(t1)
      window.clearTimeout(t2)
    }
  }, [])

  // Keep one clearly highlighted target among remaining shards
  useEffect(() => {
    if (phase !== 'collect') return
    if (collected.has(activeId) || activeId >= shards.length) {
      const next = shards.find((s) => !collected.has(s.id))
      if (next) setActiveId(next.id)
    }
  }, [activeId, collected, phase, shards])

  useEffect(() => {
    if (collected.size < shards.length) return
    setPhase('assemble')
    const t1 = window.setTimeout(() => setPhase('reveal'), 1100)
    const t2 = window.setTimeout(() => setPhase('leaving'), 2700)
    const t3 = window.setTimeout(() => doneRef.current(), 3500)
    return () => {
      window.clearTimeout(t1)
      window.clearTimeout(t2)
      window.clearTimeout(t3)
    }
  }, [collected.size, shards.length])

  function collect(id: number) {
    if (phase !== 'collect') return
    setCollected((prev) => {
      if (prev.has(id)) return prev
      const next = new Set(prev)
      next.add(id)
      return next
    })
  }

  const progress = collected.size / shards.length
  const canTap = phase === 'collect'

  return (
    <div
      className={`quest quest--${phase}`}
      role="dialog"
      aria-modal="true"
      aria-label="3D квест: собери сердце"
    >
      <div className="quest__stars" aria-hidden="true">
        {Array.from({ length: 48 }, (_, i) => (
          <span
            key={i}
            className="quest__star"
            style={{
              left: `${(i * 17 + 3) % 100}%`,
              top: `${(i * 29 + 7) % 100}%`,
              animationDelay: `${(i % 8) * 0.4}s`,
              width: `${1 + (i % 3)}px`,
              height: `${1 + (i % 3)}px`,
            }}
          />
        ))}
      </div>
      <div className="quest__nebula" aria-hidden="true" />
      <div className="quest__vignette" aria-hidden="true" />

      <header className="quest__hud">
        <p className="quest__eyebrow">cutscene · level 01</p>
        <h2 className="quest__title">
          {phase === 'boot' && 'подожди…'}
          {phase === 'shatter' && 'сердце разлетелось'}
          {phase === 'collect' && `собери его снова, ${site.herName}`}
          {(phase === 'assemble' || phase === 'reveal') && 'вот оно'}
          {phase === 'leaving' && 'для тебя'}
        </h2>
        <p className="quest__hint">
          {phase === 'boot' && 'загрузка кадра'}
          {phase === 'shatter' && 'смотри…'}
          {phase === 'collect' && 'тапай по яркому осколку'}
          {phase === 'assemble' && 'собирается…'}
          {phase === 'reveal' && 'бьётся'}
          {phase === 'leaving' && 'открываю письмо'}
        </p>
      </header>

      <div className="quest__viewport">
        <div className="quest__stage" aria-hidden={phase === 'boot'}>
          <div className="quest__floor" aria-hidden="true" />
          <div className="quest__core" aria-hidden="true">
            <div
              className={`quest__heart3d ${phase === 'boot' || phase === 'shatter' ? 'is-whole' : ''} ${phase === 'assemble' || phase === 'reveal' || phase === 'leaving' ? 'is-assembled' : ''} ${phase === 'reveal' || phase === 'leaving' ? 'is-beating' : ''}`}
            >
              <svg viewBox="0 0 24 24">
                <defs>
                  <linearGradient id="heartGrad" x1="0" y1="0" x2="1" y2="1">
                    <stop offset="0%" stopColor="#ff8fa3" />
                    <stop offset="55%" stopColor="#ff4d6d" />
                    <stop offset="100%" stopColor="#c9184a" />
                  </linearGradient>
                </defs>
                <path
                  fill="url(#heartGrad)"
                  d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"
                />
              </svg>
            </div>
            <div className="quest__ring" />
            <div className="quest__ring quest__ring--2" />
          </div>

          {shards.map((shard) => {
            const home =
              collected.has(shard.id) ||
              phase === 'assemble' ||
              phase === 'reveal' ||
              phase === 'leaving'
            const isActive = canTap && !home && shard.id === activeId
            const orbitX = 50 + Math.cos(shard.angle) * shard.radius
            const orbitY = 50 + Math.sin(shard.angle) * shard.radius * 0.78
            const left = home ? shard.homeX : orbitX
            const top = home ? shard.homeY : orbitY

            return (
              <button
                key={shard.id}
                type="button"
                className={`quest__shard ${home ? 'is-home' : 'is-loose'} ${isActive ? 'is-active' : ''} ${phase === 'boot' ? 'is-hidden' : ''}`}
                style={
                  {
                    left: `${left}%`,
                    top: `${top}%`,
                    width: shard.size,
                    height: shard.size,
                    zIndex: isActive ? 30 : home ? 5 : 10 + shard.id,
                    '--spin': `${shard.spin}deg`,
                    '--delay': `${shard.id * 0.05}s`,
                  } as CSSProperties
                }
                onClick={() => collect(shard.id)}
                disabled={!canTap || home}
                aria-label={home ? 'Уже собрано' : isActive ? 'Взять яркий осколок' : 'Взять осколок'}
              >
                <span className="quest__hit" aria-hidden="true" />
                <span className="quest__shard-visual" aria-hidden="true">
                  <span className="quest__shard-glow" />
                  <svg viewBox="0 0 24 24">
                    <path
                      fill="currentColor"
                      d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"
                    />
                  </svg>
                </span>
              </button>
            )
          })}
        </div>
      </div>

      <footer className="quest__footer">
        <div className="quest__bar">
          <span style={{ width: `${progress * 100}%` }} />
        </div>
        <p className="quest__count">
          {phase === 'collect' ? `${collected.size} / ${shards.length}` : '\u00A0'}
        </p>
      </footer>
    </div>
  )
}
