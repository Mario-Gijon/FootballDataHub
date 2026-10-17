import type { MouseEvent } from "react";

export function navigateOnPlainClick(
  event: MouseEvent<HTMLAnchorElement>,
  path: string,
  onNavigate: (path: string) => void,
): void {
  const target = event.currentTarget.target;
  if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey
    || (target !== "" && target !== "_self") || event.currentTarget.hasAttribute("download")) return;
  event.preventDefault();
  onNavigate(path);
}
