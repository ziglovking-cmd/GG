"use client";

import { PHONE_TEL } from "@/lib/guest-ui";

export const TEL_HREF = `tel:${PHONE_TEL}`;

export function CallLink({
  className,
  children,
}: {
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <a
      href={TEL_HREF}
      className={className}
      onClick={(e) => {
        e.preventDefault();
        window.location.href = TEL_HREF;
      }}
    >
      {children}
    </a>
  );
}
