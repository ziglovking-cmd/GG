export type WifiNetwork = { ssid?: string; password?: string };

export function parseWifi(text: string): { networks: WifiNetwork[]; note: string } {
  const networks: WifiNetwork[] = [];
  let pending: string[] = [];
  const rest: string[] = [];

  const prepared = text
    .replace(/\r/g, "\n")
    .replace(/wi[\s\-‑]?fi\s*:/gi, "\n")
    .replace(/(?<=\S)(?=(сеть|пароль|логин|имя(?:\s*сети)?|ssid)\s*:)/gi, "\n");

  const flushPassword = (pw: string) => {
    const password = pw.replace(/^["«]|["»]$/g, "").trim();
    const ssids = pending.length ? pending : [""];
    pending = [];
    for (const ssid of ssids) {
      if (ssid || password) networks.push({ ssid: ssid || undefined, password: password || undefined });
    }
  };

  for (const raw of prepared.split("\n")) {
    const line = raw.trim().replace(/^["«]|["»]$/g, "").trim();
    if (!line) continue;
    const low = line.toLowerCase().replace(/:$/, "");
    if (["или", "or", "wifi", "wi-fi", "wi‑fi"].includes(low)) continue;
    const net = line.match(/^(сеть|ssid|логин|имя(?:\s*сети)?)\s*[:—-]\s*(.*)$/i);
    if (net) {
      const val = net[2].trim();
      if (val) pending.push(...val.split(/\/\s+/).map((s) => s.trim()).filter(Boolean));
      continue;
    }
    const netBare = line.match(/^сеть\s+(?!.*:)(.+)$/i);
    if (netBare) {
      pending.push(netBare[1].trim());
      continue;
    }
    const pas = line.match(/^(пароль|password|pass)\s*[:—-]\s*(.*)$/i);
    if (pas) {
      flushPassword(pas[2]);
      continue;
    }
    if (pending.length && !/^\S+\s*:/.test(line)) {
      pending.push(line);
      continue;
    }
    rest.push(raw);
  }
  for (const ssid of pending) networks.push({ ssid });

  return { networks, note: rest.join("\n").trim() };
}
