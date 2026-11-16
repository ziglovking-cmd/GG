/**
 * Smoke test: price + tomorrow 19:00 → booking created
 * Run: npm run demo  (server must be up on :3000)
 */

const BASE = process.env.BASE_URL || "http://127.0.0.1:3000";

async function main() {
  const s = await fetch(`${BASE}/api/session`, { method: "POST" }).then((r) =>
    r.json()
  );
  console.log("session", s.sessionId);

  const chat = async (message) => {
    const res = await fetch(`${BASE}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sessionId: s.sessionId, message }),
    });
    const data = await res.json();
    console.log("\n> " + message);
    console.log(data.reply);
    console.log("status:", data.status, "actions:", data.actions);
    return data;
  };

  await chat("сколько стоит чистка и можно завтра в 19:00?");
  await chat("Иван");
  const last = await chat("89991234567");

  if (last.status !== "created" || !last.lead) {
    console.error("\nFAIL: expected created lead");
    process.exit(1);
  }
  console.log("\nOK: lead", last.lead.id);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
