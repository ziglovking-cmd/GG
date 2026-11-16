import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "АйАдмин — ИИ-администратор стоматологии",
  description:
    "Демо: отвечает 24/7, записывает на приём и эскалирует живому админу в Telegram",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ru">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link
          rel="preconnect"
          href="https://fonts.gstatic.com"
          crossOrigin="anonymous"
        />
        <link
          href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
