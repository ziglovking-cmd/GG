import { DocIcon, FolderIcon } from "@/components/guide/KaitenIcons";

export function DocList({
  items,
}: {
  items: { href: string; title: string; folder?: boolean }[];
}) {
  return (
    <ul className="m-0 list-none p-0">
      {items.map((item) => (
        <li key={item.href}>
          <a
            href={item.href}
            className="flex items-center gap-4 rounded px-2 py-2 no-underline hover:bg-black/[0.04] hover:no-underline"
          >
            <span className="text-[rgba(0,0,0,0.54)]">{item.folder ? <FolderIcon /> : <DocIcon />}</span>
            <span className="text-[16px] leading-[1.75]">{item.title}</span>
          </a>
        </li>
      ))}
    </ul>
  );
}
