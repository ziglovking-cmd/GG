/** «лориен» = «Лориэн», «трехполье» = «Трёхполье», пробелы и дефисы не мешают. */
export function foldSearch(s: string): string {
  return (s || "")
    .normalize("NFC")
    .toLowerCase()
    .replace(/ё/g, "е")
    .replace(/э/g, "е")
    .replace(/[^a-zа-я0-9]+/g, "");
}

export function matchesSearch(haystack: string, query: string): boolean {
  const q = foldSearch(query);
  if (!q) return true;
  return foldSearch(haystack).includes(q);
}
