import { sql } from "@/lib/db";
import type { Deposit, Player } from "@/lib/types";

export async function createDeposit(input: {
  playerId: number;
  amountRub: number;
  method?: string;
}): Promise<{ ok: true; deposit: Deposit } | { ok: false; error: string }> {
  const amount = Math.floor(input.amountRub);
  if (!Number.isFinite(amount) || amount < 50 || amount > 10000) {
    return { ok: false, error: "Сумма от 50 до 10 000₽" };
  }
  const rows = await sql<Deposit>(
    `insert into deposits (player_id, amount_rub, status, method)
     values ($1, $2, 'pending', $3) returning *`,
    [input.playerId, amount, input.method ?? "manual"],
  );
  return { ok: true, deposit: rows[0] };
}

/** Demo/sandbox top-up when no payment provider is configured. */
export async function sandboxConfirmDeposit(
  depositId: number,
): Promise<{ ok: true; player: Player; deposit: Deposit } | { ok: false; error: string }> {
  const provider = process.env.PAYMENT_PROVIDER?.trim();
  if (provider && provider !== "sandbox") {
    return { ok: false, error: "Sandbox недоступен при подключённой оплате" };
  }
  return confirmDeposit(depositId);
}

export async function confirmDeposit(
  depositId: number,
): Promise<{ ok: true; player: Player; deposit: Deposit } | { ok: false; error: string }> {
  const deps = await sql<Deposit>(
    `select * from deposits where id = $1`,
    [depositId],
  );
  const deposit = deps[0];
  if (!deposit) return { ok: false, error: "Платёж не найден" };
  if (deposit.status === "confirmed") {
    const player = (
      await sql<Player>(`select * from players where id = $1`, [deposit.player_id])
    )[0];
    return { ok: true, player, deposit };
  }
  if (deposit.status !== "pending") {
    return { ok: false, error: "Платёж уже обработан" };
  }

  await sql(
    `update deposits set status = 'confirmed', confirmed_at = now() where id = $1`,
    [depositId],
  );
  const players = await sql<Player>(
    `update players set balance_rub = balance_rub + $2 where id = $1 returning *`,
    [deposit.player_id, deposit.amount_rub],
  );
  const updated = (
    await sql<Deposit>(`select * from deposits where id = $1`, [depositId])
  )[0];
  return { ok: true, player: players[0], deposit: updated };
}

export async function chargeEntry(
  playerId: number,
  amount: number,
): Promise<{ ok: true; player: Player } | { ok: false; error: string }> {
  const players = await sql<Player>(
    `update players set balance_rub = balance_rub - $2
     where id = $1 and balance_rub >= $2
     returning *`,
    [playerId, amount],
  );
  if (!players[0]) {
    return { ok: false, error: `Недостаточно средств. Нужно ${amount}₽ на балансе` };
  }
  return { ok: true, player: players[0] };
}

export async function listDeposits(playerId: number): Promise<Deposit[]> {
  return sql<Deposit>(
    `select * from deposits where player_id = $1 order by id desc limit 20`,
    [playerId],
  );
}

export async function listPendingDeposits(): Promise<
  Array<Deposit & { display_name: string; brawl_tag: string }>
> {
  return sql(
    `select d.*, p.display_name, p.brawl_tag
     from deposits d
     join players p on p.id = d.player_id
     where d.status = 'pending'
     order by d.id asc`,
  );
}
