"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { NavLink } from "@/components/layout/NavLink";
import { Icon, type IconName } from "@/components/ui/Icon";
import { readTokenClaims } from "@/lib/auth/tokenClaims";
import { useAuth } from "@/lib/auth/useAuth";
import { isEndUserPath } from "@/lib/sessionIdentity";

import "./console.css";

interface NavItem {
  href: string;
  label: string;
  icon: IconName;
}

/** The staff console's sections, grouped the way the firm uses them. */
const NAV_GROUPS: { label: string; links: NavItem[] }[] = [
  {
    label: "Overview",
    links: [
      { href: "/dashboard", label: "Dashboard", icon: "dashboard" },
      { href: "/analytics", label: "Analytics", icon: "analytics" },
      { href: "/activity", label: "Activity", icon: "activity" },
    ],
  },
  {
    label: "Library",
    links: [
      { href: "/vault", label: "Vault", icon: "vault" },
      { href: "/research", label: "Research", icon: "research" },
    ],
  },
  {
    label: "Clients",
    links: [
      { href: "/matters", label: "Matters", icon: "matters" },
      { href: "/requests", label: "Requests", icon: "requests" },
      { href: "/users", label: "Users", icon: "users" },
    ],
  },
  {
    label: "Setup",
    links: [
      { href: "/intake-checklist", label: "Intake questions", icon: "intake" },
      { href: "/prompts", label: "Prompts", icon: "prompts" },
      { href: "/settings", label: "Settings", icon: "settings" },
      { href: "/billing", label: "Billing", icon: "billing" },
    ],
  },
];

/** "Library › Vault" for the current page (and "Clients › Matters › Case" below a matter). */
function breadcrumb(pathname: string | null): string[] {
  for (const group of NAV_GROUPS) {
    for (const link of group.links) {
      if (pathname === link.href) return [group.label, link.label];
      if (pathname?.startsWith(`${link.href}/`)) {
        const rest = pathname.slice(link.href.length + 1);
        const detail = link.href === "/matters" ? "Case" : link.href === "/vault" && rest === "dropbox" ? "Dropbox" : null;
        return detail ? [group.label, link.label, detail] : [group.label, link.label];
      }
    }
  }
  return [];
}

function Brand({ subtitle }: { subtitle: string }) {
  return (
    <Link href="/" className="c-brand" aria-label="AshiLegal home">
      <span className="c-logo" aria-hidden>
        A
      </span>
      <span>
        <b>AshiLegal</b>
        <small>{subtitle}</small>
      </span>
    </Link>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const { isAuthenticated, isLoading, token, logout } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const [menuOpen, setMenuOpen] = useState(false);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const userMenuRef = useRef<HTMLDivElement>(null);

  // Close the account menu on a click outside it or on Escape.
  useEffect(() => {
    if (!userMenuOpen) return;
    const onClick = (event: MouseEvent) => {
      if (!userMenuRef.current?.contains(event.target as Node)) setUserMenuOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setUserMenuOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [userMenuOpen]);

  // The client portal draws its own header and page (app/(client)/layout.tsx).
  if (isEndUserPath(pathname)) {
    return <>{children}</>;
  }

  function handleLogout() {
    setUserMenuOpen(false);
    logout();
    router.push("/login");
  }

  // Session still being read from storage: no chrome yet, so nothing flickers.
  if (isLoading) {
    return (
      <div className="console">
        <main>{children}</main>
      </div>
    );
  }

  // Signed out (welcome page, administrator sign-in): a public top bar, no console navigation.
  if (!isAuthenticated) {
    return (
      <div className="console">
        <a href="#main" className="c-skip">
          Skip to content
        </a>
        <header className="c-public-bar">
          <div className="c-public-inner">
            <Brand subtitle="Legal research" />
            <nav className="c-public-links" aria-label="Sign in">
              <Link href="/portal/login">Client sign in</Link>
              <Link href="/login" className="c-button-link">
                Firm staff
              </Link>
            </nav>
          </div>
        </header>
        <main id="main">{children}</main>
      </div>
    );
  }

  const claims = token ? readTokenClaims(token) : null;
  const email = claims?.email ?? "";
  const crumbs = breadcrumb(pathname);

  return (
    <div className="console">
      <a href="#main" className="c-skip">
        Skip to content
      </a>
      <div className="c-shell">
        <aside className={`c-side${menuOpen ? " is-open" : ""}`} aria-label="Console navigation">
          <div className="c-side-head">
            <Brand subtitle="Firm console" />
            <button type="button" className="c-icon-button c-only-mobile" onClick={() => setMenuOpen(false)} aria-label="Close menu">
              <Icon name="close" />
            </button>
          </div>
          {/* Any link clicked closes the menu on phones. */}
          <nav
            className="c-nav"
            aria-label="Console"
            onClick={(event) => {
              if ((event.target as HTMLElement).closest("a")) setMenuOpen(false);
            }}
          >
            {NAV_GROUPS.map((group) => (
              <div key={group.label} className="c-group">
                <div className="c-group-label">{group.label}</div>
                {group.links.map((link) => (
                  <NavLink key={link.href} href={link.href} icon={link.icon}>
                    {link.label}
                  </NavLink>
                ))}
              </div>
            ))}
          </nav>
          <div className="c-side-foot">Answers come only from your firm&apos;s library.</div>
        </aside>
        {menuOpen && <div className="c-scrim" onClick={() => setMenuOpen(false)} aria-hidden />}

        <div className="c-body">
          <header className="c-topbar">
            <button type="button" className="c-icon-button c-only-mobile" onClick={() => setMenuOpen(true)} aria-label="Open menu">
              <Icon name="menu" />
            </button>
            <nav className="c-crumbs" aria-label="Breadcrumb">
              {crumbs.map((crumb, index) => (
                <span key={crumb} aria-current={index === crumbs.length - 1 ? "page" : undefined}>
                  {index > 0 && <Icon name="chevronRight" size={14} />}
                  {crumb}
                </span>
              ))}
            </nav>
            <div className="c-account" ref={userMenuRef}>
              <button
                type="button"
                className="c-account-button"
                onClick={() => setUserMenuOpen((open) => !open)}
                aria-haspopup="menu"
                aria-expanded={userMenuOpen}
              >
                <span className="c-avatar" aria-hidden>
                  {(email[0] ?? "?").toUpperCase()}
                </span>
                <span className="c-account-name">{email}</span>
                <Icon name="chevronDown" size={16} />
              </button>
              {userMenuOpen && (
                <div className="c-account-menu" role="menu">
                  <div className="c-account-who">
                    <strong>{email}</strong>
                    {claims?.role && <span>{claims.role}</span>}
                  </div>
                  <button type="button" role="menuitem" onClick={handleLogout}>
                    <Icon name="logout" size={16} /> Log out
                  </button>
                </div>
              )}
            </div>
          </header>
          <main id="main" className="c-main">
            {children}
          </main>
        </div>
      </div>
    </div>
  );
}
