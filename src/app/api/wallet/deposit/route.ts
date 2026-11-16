import { requireAdmin } from "@/lib/auth";
import { playerFromRequest } from "@/lib/players";
import {
  confirmDeposit,
  createDeposit,
  listPendingDeposits,
  sandboxConfirmDeposit,
} from "@/lib/wallet";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  if (!requireAdmin(request)) {
    return Response.json({ error: "admin only" }, { status: 401 });
  }
  return Response.json({ pending: await listPendingDeposits() });
}

export async function POST(request: Request) {
  const body = (await request.json().catch(() => ({}))) as {
    amountRub?: number;
    confirmId?: number;
    sandbox?: boolean;
  };

  if (body.confirmId) {
    if (!requireAdmin(request) && !body.sandbox) {
      return Response.json({ error: "admin only" }, { status: 401 });
    }
    const res = body.sandbox
      ? await sandboxConfirmDeposit(body.confirmId)
      : await confirmDeposit(body.confirmId);
    if (!res.ok) return Response.json({ error: res.error }, { status: 400 });
    return Response.json(res);
  }

  const player = await playerFromRequest(request);
  if (!player) {
    return Response.json({ error: "Войди на сайте" }, { status: 401 });
  }

  const created = await createDeposit({
    playerId: player.id,
    amountRub: Number(body.amountRub ?? 50),
  });
  if (!created.ok) {
    return Response.json({ error: created.error }, { status: 400 });
  }

  // Auto-sandbox confirm in local/demo when no payment provider
  const provider = process.env.PAYMENT_PROVIDER?.trim();
  if (!provider || provider === "sandbox") {
    const confirmed = await sandboxConfirmDeposit(created.deposit.id);
    return Response.json({
      ...confirmed,
      sample: true,
      hint: "Демо-пополнение: деньги зачислены сразу. Для боевых платежей задай PAYMENT_PROVIDER.",
    });
  }

  return Response.json({
    deposit: created.deposit,
    hint: "Переведи сумму организатору — после подтверждения баланс обновится.",
  });
}
