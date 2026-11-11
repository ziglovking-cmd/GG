export function isCoffeeVideo(v: { title?: string; name?: string; q?: string; filename?: string }) {
  const blob = `${v.title || ""} ${v.name || ""} ${v.q || ""} ${v.filename || ""}`
    .normalize("NFC")
    .toLowerCase();
  return blob.includes("кофемаш") || blob.includes("кофевар") || blob.includes("coffee");
}
