"use client";

import Link, { useLinkStatus } from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { Icon, type IconName } from "@/components/ui/Icon";

/**
 * A navigation link that shows the click registered. In development Next.js
 * doesn't prefetch, so a page can take a moment to arrive; without a sign
 * the click looks ignored and people click again. The current page's link
 * is marked (aria-current) and bold.
 */
export function NavLink({ href, children, icon }: { href: string; children: ReactNode; icon?: IconName }) {
  const pathname = usePathname();
  const isCurrent = pathname === href || (pathname?.startsWith(`${href}/`) ?? false);

  return (
    <Link href={href} aria-current={isCurrent ? "page" : undefined} style={{ fontWeight: isCurrent ? 700 : 400 }}>
      {icon && <Icon name={icon} />}
      <span>{children}</span>
      <PendingHint />
    </Link>
  );
}

function PendingHint() {
  const { pending } = useLinkStatus();
  // Always rendered at a fixed width so showing it never shifts the layout.
  return (
    <span
      aria-hidden
      className="nav-pending"
      style={{ display: "inline-block", width: "1.2em", marginLeft: "0.15em", opacity: pending ? 1 : 0 }}
    >
      …
    </span>
  );
}
