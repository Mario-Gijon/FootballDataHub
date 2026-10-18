import type { AnchorHTMLAttributes } from "react";
import { navigateOnPlainClick } from "../domain/internal-navigation";
import { matchPath } from "../domain/matches";

type InternalMatchLinkProps = Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href" | "onClick"> & {
  internalId: string;
  onNavigate: (path: string) => void;
};

/** Plain clicks stay in FootballDataHub; modified clicks keep native link behavior. */
export function InternalMatchLink({ internalId, onNavigate, children, ...anchorProps }: InternalMatchLinkProps) {
  const path = matchPath(internalId);
  return <a
    {...anchorProps}
    href={path}
    onClick={(event) => navigateOnPlainClick(event, path, onNavigate)}
  >{children}</a>;
}
