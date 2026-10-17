import type { AnchorHTMLAttributes } from "react";
import { navigateOnPlainClick } from "../domain/internal-navigation";
import { playerPath } from "../domain/players";

type InternalPlayerLinkProps = Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href" | "onClick"> & {
  playerId: number;
  onNavigate: (path: string) => void;
};

/** A plain click stays inside FootballDataHub; modified clicks remain native browser links. */
export function InternalPlayerLink({ playerId, onNavigate, children, ...anchorProps }: InternalPlayerLinkProps) {
  const path = playerPath(playerId);
  return <a
    {...anchorProps}
    href={path}
    onClick={(event) => navigateOnPlainClick(event, path, onNavigate)}
  >{children}</a>;
}
