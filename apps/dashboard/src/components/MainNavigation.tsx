import type { MouseEvent } from "react";

export type MainPage = "competitions" | "teams" | "players";

interface Props {
  activePage: MainPage;
  onNavigate: (path: string) => void;
}

export function MainNavigation({ activePage, onNavigate }: Props) {
  function navigate(event: MouseEvent<HTMLAnchorElement>, path: string) {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    onNavigate(path);
  }

  return (
    <nav className="main-navigation" aria-label="Navegación principal">
      <a href="/" aria-current={activePage === "competitions" ? "page" : undefined} className={activePage === "competitions" ? "is-active" : ""} onClick={(event) => navigate(event, "/")}>Competiciones</a>
      <a href="/teams" aria-current={activePage === "teams" ? "page" : undefined} className={activePage === "teams" ? "is-active" : ""} onClick={(event) => navigate(event, "/teams")}>Equipos</a>
      <a href="/players" aria-current={activePage === "players" ? "page" : undefined} className={activePage === "players" ? "is-active" : ""} onClick={(event) => navigate(event, "/players")}>Jugadores</a>
    </nav>
  );
}
