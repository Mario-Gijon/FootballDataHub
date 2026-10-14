import type { AnchorHTMLAttributes, MouseEvent } from "react";
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
    onClick={(event: MouseEvent<HTMLAnchorElement>) => {
      const target = event.currentTarget.target;
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey
        || (target !== "" && target !== "_self") || event.currentTarget.hasAttribute("download")) return;
      event.preventDefault();
      onNavigate(path);
    }}
  >{children}</a>;
}
