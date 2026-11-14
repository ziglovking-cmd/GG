import { useEffect, useRef, useState, type CSSProperties, type MouseEvent, type RefObject } from 'react'
import { site } from './config'
import './App.css'

const letterParagraphs = [
  `Дорогая ${site.herName},`,
  'Иногда слова кажутся слишком маленькими для того, что я чувствую. Поэтому я собрал их здесь — медленно, бережно, как букет.',
  'Спасибо, что ты есть. Спасибо за твои глаза, за твою честность, за то, как ты делаешь обычное — особенным. Я люблю тебя не за идеальный день. Я люблю тебя во всех твоих настоящих.',
  'Если когда-нибудь станет тяжело или тихо — открой эту страницу снова. Я всё ещё здесь. И всё ещё выбираю тебя.',
]

function useReveal() {
  const ref = useRef<HTMLElement | null>(null)

  useEffect(() => {
    const node = ref.current
    if (!node) return

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            entry.target.classList.add('is-visible')
            observer.unobserve(entry.target)
          }
        }
      },
      { threshold: 0.18, rootMargin: '0px 0px -8% 0px' },
    )

    const targets = node.querySelectorAll('.reveal')
    targets.forEach((el) => observer.observe(el))
    return () => observer.disconnect()
  }, [])

  return ref
}

type Spark = { id: number; x: number; y: number; tx: string; ty: string }

export default function App() {
  const pageRef = useReveal()
  const [sparks, setSparks] = useState<Spark[]>([])
  const sparkId = useRef(0)

  const petals = Array.from({ length: 12 }, (_, i) => ({
    id: i,
    left: `${6 + ((i * 17) % 88)}%`,
    delay: `${i * 0.7}s`,
    duration: `${10 + (i % 5) * 1.4}s`,
    size: `${8 + (i % 4) * 2}px`,
    opacity: 0.18 + (i % 5) * 0.05,
  }))

  function burstHearts(event: MouseEvent<HTMLButtonElement>) {
    const rect = event.currentTarget.getBoundingClientRect()
    const originX = rect.left + rect.width / 2
    const originY = rect.top + rect.height / 2
    const next: Spark[] = Array.from({ length: 10 }, () => {
      const angle = Math.random() * Math.PI * 2
      const dist = 48 + Math.random() * 70
      sparkId.current += 1
      return {
        id: sparkId.current,
        x: originX,
        y: originY,
        tx: `${Math.cos(angle) * dist}px`,
        ty: `${Math.sin(angle) * dist - 20}px`,
      }
    })
    setSparks((prev) => [...prev, ...next])
    window.setTimeout(() => {
      setSparks((prev) => prev.filter((s) => !next.some((n) => n.id === s.id)))
    }, 950)
  }

  useEffect(() => {
    document.title = `Для ${site.herName}`
  }, [])

  return (
    <div className="page" ref={pageRef as RefObject<HTMLDivElement>}>
      <div className="petals" aria-hidden="true">
        {petals.map((p) => (
          <span
            key={p.id}
            className="petal"
            style={{
              left: p.left,
              width: p.size,
              height: `calc(${p.size} * 1.35)`,
              animationDelay: p.delay,
              animationDuration: p.duration,
              opacity: p.opacity,
            }}
          />
        ))}
      </div>

      <header className="hero">
        <div className="hero__media" aria-hidden="true">
          <img src="/hero.jpg" alt="" />
          <div className="hero__veil" />
        </div>
        <div className="hero__content">
          <p className="brand">{site.herName}</p>
          <h1 className="hero__headline">{site.headline}</h1>
          <p className="hero__tagline">{site.tagline}</p>
          <a className="cta" href="#letter">
            <span className="cta__heart" aria-hidden="true" />
            {site.cta}
          </a>
        </div>
        <div className="scroll-hint" aria-hidden="true" />
      </header>

      <section className="section" aria-labelledby="reasons-title">
        <p className="section__eyebrow reveal">для тебя</p>
        <h2 id="reasons-title" className="section__title reveal">
          {site.reasonsTitle}
        </h2>
        <p className="section__lead reveal">{site.reasonsLead}</p>
        <div className="reasons">
          {site.reasons.map((reason, index) => (
            <article className="reason reveal" key={reason.title}>
              <span className="reason__index">0{index + 1}</span>
              <h3 className="reason__title">{reason.title}</h3>
              <p className="reason__text">{reason.text}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="letter" id="letter" aria-labelledby="letter-title">
        <div className="letter__inner">
          <div className="letter__visual reveal">
            <img src="/letter.jpg" alt="Письмо при свечах и лепесток розы" />
          </div>
          <div className="letter__copy">
            <p className="section__eyebrow reveal">личное</p>
            <h2 id="letter-title" className="section__title reveal">
              {site.letterTitle}
            </h2>
            {letterParagraphs.map((paragraph) => (
              <p className="letter__body reveal" key={paragraph.slice(0, 24)}>
                {paragraph}
              </p>
            ))}
            <p className="letter__sign reveal">— {site.fromName}</p>
          </div>
        </div>
      </section>

      <section className="section closing" aria-labelledby="closing-title">
        <p className="section__eyebrow reveal">навсегда</p>
        <h2 id="closing-title" className="section__title reveal">
          {site.closingTitle}
        </h2>
        <p className="closing__text reveal">{site.closingText}</p>
        <button
          type="button"
          className="heart-burst reveal"
          onClick={burstHearts}
          aria-label="Отправить сердечко"
        >
          <svg className="heart-burst__icon" viewBox="0 0 24 24" aria-hidden="true">
            <path
              fill="currentColor"
              d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"
            />
          </svg>
        </button>
      </section>

      <footer className="footer">сделано с любовью</footer>

      {sparks.map((spark) => (
        <span
          key={spark.id}
          className="spark"
          style={
            {
              left: spark.x,
              top: spark.y,
              '--tx': spark.tx,
              '--ty': spark.ty,
            } as CSSProperties
          }
        />
      ))}
    </div>
  )
}
