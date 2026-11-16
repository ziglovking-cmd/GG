import type { Metadata } from "next";
import { Bebas_Neue, Manrope } from "next/font/google";
import { SiteNav } from "@/components/SiteNav";
import "./globals.css";

const display = Bebas_Neue({
  weight: "400",
  subsets: ["latin"],
  variable: "--font-display",
});

const body = Manrope({
  subsets: ["latin", "cyrillic"],
  variable: "--font-body",
});

export const metadata: Metadata = {
  title: "GG Cup — Brawl Stars турики",
  description:
    "Турниры Brawl Stars: вход 50₽, приз 150₽, сетки, стрим и чек-ин в комнату за 60 секунд.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ru">
      <body className={`${display.variable} ${body.variable} antialiased`}>
        <div className="noise" aria-hidden />
        <div className="site-shell font-[family-name:var(--font-body)]">
          <SiteNav />
          {children}
        </div>
      </body>
    </html>
  );
}
