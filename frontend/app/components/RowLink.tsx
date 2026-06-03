"use client";

import clsx from "clsx";
import { useRouter } from "next/navigation";

/** A full-row clickable that navigates on click but lets inner buttons (e.g. CopyId,
 * which stops propagation) work without invalid <button>-inside-<a> nesting. */
export function RowLink({
  href,
  children,
  className,
}: {
  href: string;
  children: React.ReactNode;
  className?: string;
}) {
  const router = useRouter();
  return (
    <div
      role="link"
      tabIndex={0}
      onClick={() => router.push(href)}
      onKeyDown={(e) => {
        if (e.key === "Enter") router.push(href);
      }}
      className={clsx("cursor-pointer", className)}
    >
      {children}
    </div>
  );
}
