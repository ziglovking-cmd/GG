import ChatWidget from "@/components/ChatWidget";
import { clinic } from "@/lib/clinic";

export default function HomePage() {
  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">А</div>
          <div>
            <h1>АйАдмин</h1>
            <p>ИИ-администратор для стоматологии</p>
          </div>
        </div>
        <nav className="nav">
          <a href="/admin">Админка / заявки</a>
          <span className="chip">MVP демо</span>
        </nav>
      </header>

      <div className="hero-grid">
        <section className="pitch">
          <div className="kicker">60 секунд до «вау»</div>
          <h2>Пациент пишет — заявка у админа</h2>
          <p className="lead">
            Бот клиники «{clinic.name}» отвечает из базы знаний, ведёт к записи
            и шлёт карточку живому администратору в Telegram.
          </p>

          <div className="meta-row">
            <div>
              <strong>Адрес</strong>
              <div>{clinic.address}</div>
            </div>
            <div>
              <strong>Часы</strong>
              <div>
                {clinic.hours}, {clinic.hoursNote}
              </div>
            </div>
            <div>
              <strong>Прайс «от»</strong>
              <div>гигиена 4 500 · кариес 6 000 · имплант 45 000</div>
            </div>
          </div>

          <p className="lead" style={{ marginTop: "1.4rem" }}>
            Критерий готовности: спросите «сколько стоит чистка и можно завтра в
            19:00?» — получите цену, слот, подтверждение и заявку в{" "}
            <a href="/admin">/admin</a>.
          </p>
        </section>

        <ChatWidget />
      </div>
    </main>
  );
}
