import type { Bracket, BracketMatch, Registration, SlotStatus } from "@/lib/types";

type SeedPlayer = Pick<
  Registration,
  "player_id" | "brawl_tag" | "display_name" | "id" | "ready_status"
>;

export function buildBracket(paid: SeedPlayer[]): Bracket {
  const n = nextPowerOfTwo(Math.max(2, paid.length));
  const rounds = Math.log2(n);
  const seeded: SeedPlayer[] = [...paid];
  while (seeded.length < n) {
    seeded.push({
      id: -seeded.length,
      player_id: -seeded.length,
      brawl_tag: "BYE",
      display_name: "BYE",
      ready_status: "bot",
    });
  }

  const order = seedOrder(n);
  const placed = order.map((idx) => seeded[idx - 1]);
  const matches: BracketMatch[] = [];
  const noshowPlayerIds: number[] = [];

  for (let i = 0; i < n / 2; i++) {
    const a = placed[i * 2];
    const b = placed[i * 2 + 1];
    const slotA = toSlot(a, noshowPlayerIds);
    const slotB = toSlot(b, noshowPlayerIds);

    let winnerId: number | null = null;
    if (slotA.status === "bye" && slotB.status !== "bye") {
      winnerId = slotB.id;
    } else if (slotB.status === "bye" && slotA.status !== "bye") {
      winnerId = slotA.id;
    } else if (isOut(slotA.status) && !isOut(slotB.status)) {
      winnerId = slotB.id;
    } else if (isOut(slotB.status) && !isOut(slotA.status)) {
      winnerId = slotA.id;
    } else if (isOut(slotA.status) && isOut(slotB.status)) {
      winnerId = null;
    }

    matches.push({
      id: `r1-m${i}`,
      round: 1,
      slot: i,
      playerAId: slotA.status === "bye" ? null : slotA.id,
      playerBId: slotB.status === "bye" ? null : slotB.id,
      playerAName: slotA.name,
      playerBName: slotB.name,
      playerATag: slotA.tag,
      playerBTag: slotB.tag,
      playerAStatus: slotA.status,
      playerBStatus: slotB.status,
      winnerId,
      score: null,
    });
  }

  let prevCount = n / 2;
  for (let round = 2; round <= rounds; round++) {
    const count = prevCount / 2;
    for (let i = 0; i < count; i++) {
      const left = matches.find((m) => m.round === round - 1 && m.slot === i * 2);
      const right = matches.find(
        (m) => m.round === round - 1 && m.slot === i * 2 + 1,
      );
      const winnerA = left?.winnerId ?? null;
      const winnerB = right?.winnerId ?? null;
      matches.push({
        id: `r${round}-m${i}`,
        round,
        slot: i,
        playerAId: winnerA,
        playerBId: winnerB,
        playerAName: nameById(paid, winnerA),
        playerBName: nameById(paid, winnerB),
        playerATag: tagById(paid, winnerA),
        playerBTag: tagById(paid, winnerB),
        playerAStatus: winnerA == null ? "bye" : "active",
        playerBStatus: winnerB == null ? "bye" : "active",
        winnerId: null,
        score: null,
      });
    }
    prevCount = count;
  }

  return advanceAutoWins({ size: n, rounds, matches, noshowPlayerIds });
}

export function markNoshowInBracket(
  bracket: Bracket,
  playerId: number,
  playerMeta?: { name?: string; tag?: string },
): Bracket {
  const noshowPlayerIds = bracket.noshowPlayerIds.includes(playerId)
    ? bracket.noshowPlayerIds
    : [...bracket.noshowPlayerIds, playerId];

  const matches = bracket.matches.map((m) => {
    const next = { ...m };
    if (next.playerAId === playerId) {
      next.playerAStatus = "noshow";
      next.playerAName = `${playerMeta?.name ?? next.playerAName ?? "Игрок"} · ВЫБЫЛ`;
      next.playerBStatus =
        next.playerBStatus === "active" ? next.playerBStatus : next.playerBStatus;
      if (next.playerBId != null && !isOut(next.playerBStatus)) {
        next.winnerId = next.playerBId;
      } else if (next.round === 1) {
        // replace no-show with BOT so the match can still be shown
        next.playerAStatus = "bot";
        next.playerAName = "BOT";
        next.playerATag = "#BOT";
        next.playerAId = -100000 - Math.abs(playerId);
        if (next.playerBId != null && !isOut(next.playerBStatus)) {
          next.winnerId = next.playerBId;
        }
      }
    }
    if (next.playerBId === playerId) {
      next.playerBStatus = "noshow";
      next.playerBName = `${playerMeta?.name ?? next.playerBName ?? "Игрок"} · ВЫБЫЛ`;
      if (next.playerAId != null && !isOut(next.playerAStatus)) {
        next.winnerId = next.playerAId;
      } else if (next.round === 1) {
        next.playerBStatus = "bot";
        next.playerBName = "BOT";
        next.playerBTag = "#BOT";
        next.playerBId = -100000 - Math.abs(playerId);
        if (next.playerAId != null && !isOut(next.playerAStatus)) {
          next.winnerId = next.playerAId;
        }
      }
    }
    return next;
  });

  return advanceAutoWins({ ...bracket, matches, noshowPlayerIds });
}

export function applyMatchWinner(
  bracket: Bracket,
  matchId: string,
  winnerId: number,
): Bracket {
  const matches = bracket.matches.map((m) => ({ ...m }));
  const match = matches.find((m) => m.id === matchId);
  if (!match) return bracket;
  if (match.playerAId !== winnerId && match.playerBId !== winnerId) {
    return bracket;
  }
  match.winnerId = winnerId;
  return advanceAutoWins({ ...bracket, matches });
}

function advanceAutoWins(bracket: Bracket): Bracket {
  const matches = bracket.matches.map((m) => ({ ...m }));
  for (let round = 1; round < bracket.rounds; round++) {
    for (const match of matches.filter((m) => m.round === round)) {
      if (match.winnerId == null) continue;
      const next = matches.find(
        (m) => m.round === round + 1 && m.slot === Math.floor(match.slot / 2),
      );
      if (!next) continue;
      const isA = match.slot % 2 === 0;
      const name =
        match.winnerId === match.playerAId ? match.playerAName : match.playerBName;
      const tag =
        match.winnerId === match.playerAId ? match.playerATag : match.playerBTag;
      if (isA) {
        next.playerAId = match.winnerId;
        next.playerAName = name;
        next.playerATag = tag;
        next.playerAStatus = "active";
      } else {
        next.playerBId = match.winnerId;
        next.playerBName = name;
        next.playerBTag = tag;
        next.playerBStatus = "active";
      }
      if (
        next.playerAId != null &&
        next.playerBId != null &&
        isOut(next.playerAStatus) &&
        !isOut(next.playerBStatus)
      ) {
        next.winnerId = next.playerBId;
      } else if (
        next.playerAId != null &&
        next.playerBId != null &&
        isOut(next.playerBStatus) &&
        !isOut(next.playerAStatus)
      ) {
        next.winnerId = next.playerAId;
      }
    }
  }
  return { ...bracket, matches };
}

function toSlot(
  p: SeedPlayer,
  noshowPlayerIds: number[],
): { id: number; name: string | null; tag: string | null; status: SlotStatus } {
  if (p.brawl_tag === "BYE" || p.player_id < 0) {
    return { id: p.player_id, name: null, tag: null, status: "bye" };
  }
  if (p.ready_status === "noshow" || p.ready_status === "forfeit") {
    noshowPlayerIds.push(p.player_id);
    return {
      id: -100000 - Math.abs(p.player_id),
      name: "BOT",
      tag: "#BOT",
      status: "bot",
    };
  }
  if (p.ready_status === "bot") {
    return {
      id: -100000 - Math.abs(p.player_id),
      name: "BOT",
      tag: "#BOT",
      status: "bot",
    };
  }
  return {
    id: p.player_id,
    name: p.display_name ?? "Игрок",
    tag: p.brawl_tag,
    status: "active",
  };
}

function isOut(status: SlotStatus): boolean {
  return status === "noshow" || status === "eliminated" || status === "bot" || status === "bye";
}

function nameById(
  paid: Array<{ player_id: number; display_name?: string }>,
  id: number | null,
): string | null {
  if (id == null) return null;
  if (id < 0) return "BOT";
  return paid.find((p) => p.player_id === id)?.display_name ?? `Игрок ${id}`;
}

function tagById(
  paid: Array<{ player_id: number; brawl_tag: string }>,
  id: number | null,
): string | null {
  if (id == null) return null;
  if (id < 0) return "#BOT";
  return paid.find((p) => p.player_id === id)?.brawl_tag ?? null;
}

function nextPowerOfTwo(n: number): number {
  let p = 1;
  while (p < n) p *= 2;
  return p;
}

function seedOrder(n: number): number[] {
  let seeds = [1, 2];
  while (seeds.length < n) {
    const next: number[] = [];
    const sum = seeds.length * 2 + 1;
    for (const s of seeds) {
      next.push(s, sum - s);
    }
    seeds = next;
  }
  return seeds;
}

export function formatBracketText(bracket: Bracket): string {
  const lines = [`Сетка ${bracket.size} игроков`];
  if (bracket.noshowPlayerIds.length) {
    lines.push(`Не зашли / выбыли: ${bracket.noshowPlayerIds.length}`);
  }
  for (let r = 1; r <= bracket.rounds; r++) {
    lines.push(`\nРаунд ${r}:`);
    for (const m of bracket.matches.filter((x) => x.round === r)) {
      const a = label(m.playerAName, m.playerAStatus);
      const b = label(m.playerBName, m.playerBStatus);
      const w =
        m.winnerId == null
          ? ""
          : m.winnerId === m.playerAId
            ? " → A"
            : m.winnerId === m.playerBId
              ? " → B"
              : "";
      lines.push(`• ${a} vs ${b}${w}`);
    }
  }
  return lines.join("\n");
}

function label(name: string | null, status: SlotStatus): string {
  if (!name) return "TBD";
  if (status === "noshow") return `${name} (ВЫБЫЛ)`;
  if (status === "bot") return "BOT";
  return name;
}

export function parseBracket(raw: string | null | undefined): Bracket | null {
  if (!raw) return null;
  try {
    return JSON.parse(raw) as Bracket;
  } catch {
    return null;
  }
}
