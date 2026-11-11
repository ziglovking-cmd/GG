import { redirect } from "next/navigation";
import { AdminApp } from "@/components/AdminApp";

export const dynamic = "force-dynamic";

export default async function AdminPage({
  searchParams,
}: {
  searchParams: Promise<{ k?: string }>;
}) {
  const { k } = await searchParams;
  if (k) redirect(`/api/admin/login?k=${encodeURIComponent(k)}`);
  return <AdminApp />;
}
