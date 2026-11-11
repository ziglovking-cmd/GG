/** iPhone names from the 05.11.2026 Everest Telegram dump. */
const BY_IMG: Record<string, string> = {
  img_4720: "Как пользоваться ванной",
  img_4729: "Как работают шторы в комнате",
  img_4732: "Как пользоваться телевизором",
  img_4763: "Как пользоваться кондиционером",
  img_4770: "Как работают шторы на балконе",
};

export function everestTitleFromFilename(original: string): string {
  const base = original.replace(/\.[^.]+$/i, "").trim();
  const key = base.normalize("NFC").toLowerCase().replace(/[\s-]+/g, "_");
  const img = key.match(/img_(\d+)/);
  if (img) {
    const mapped = BY_IMG[`img_${img[1]}`];
    if (mapped) return mapped;
  }
  const low = key.replace(/_/g, " ");
  if (/балкон/.test(low) && /штор/.test(low)) return "Как работают шторы на балконе";
  if (/ванн|душ/.test(low)) return "Как пользоваться ванной";
  if (/штор/.test(low)) return "Как работают шторы";
  if (/телевиз|\btv\b/.test(low)) return "Как пользоваться телевизором";
  if (/кондиц|сплит/.test(low)) return "Как пользоваться кондиционером";
  if (/пульт/.test(low)) return "Пульты Эверест";
  return `Эверест · ${base}`;
}
