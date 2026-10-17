import type { AnchorHTMLAttributes } from "react";
import { navigateOnPlainClick } from "../domain/internal-navigation";
import { teamPath } from "../domain/teams";

type InternalTeamLinkProps = Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href" | "onClick"> & {
  teamId: number;
  onNavigate: (path: string) => void;
};

/** An ordinary click stays in the app; modified clicks retain normal browser link behavior. */
export function InternalTeamLink({ teamId, onNavigate, children, ...anchorProps }: InternalTeamLinkProps) {
  const path = teamPath(teamId);
  return <a
    {...anchorProps}
    href={path}
    onClick={(event) => navigateOnPlainClick(event, path, onNavigate)}
  >{children}</a>;
}
