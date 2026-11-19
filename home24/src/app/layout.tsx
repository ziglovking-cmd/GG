import type { Metadata } from "next";
import { Cormorant_Garamond, Manrope } from "next/font/google";
import { publicOrigin } from "@/lib/site";
import "./globals.css";

const sans = Manrope({
  subsets: ["latin", "cyrillic"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-sans",
});

const display = Cormorant_Garamond({
  subsets: ["latin", "cyrillic"],
  weight: ["500", "600", "700"],
  variable: "--font-display",
});

export const metadata: Metadata = {
  title: "Home24 — инструкция для гостей",
  description: "Инструкция по заселению: как добраться, парковка, Wi-Fi, FAQ и видео.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const origin = publicOrigin();
  return (
    <html lang="ru">
      <body className={`${sans.variable} ${display.variable} ${sans.className} bg-[#efe8dc] antialiased`}>
        <script
          dangerouslySetInnerHTML={{
            __html: `window.__HOME24_ORIGIN=${JSON.stringify(origin)};`,
          }}
        />
        {children}
      </body>
    </html>
  );
}
