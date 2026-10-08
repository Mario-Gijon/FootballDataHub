"""Sesiones CDP y navegación mediante un navegador externo administrado.

El gestor nunca depende de pestañas abiertas por el usuario: crea páginas propias.
Las páginas devueltas deben cerrarse con ``visit.close()`` después de usarlas.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from .browser_runtime import BrowserRuntime, BrowserRuntimeConfig, start_browser


class BrowserSessionError(RuntimeError):
    """No se pudo establecer la sesión CDP."""


class BrowserNavigationError(BrowserSessionError):
    """Falló la navegación (no implica necesariamente un desafío Cloudflare)."""


@dataclass(slots=True)
class PageVisit:
    page: Any
    requested_url: str
    response_status: int | None
    _closed: bool = False

    @property
    def final_url(self) -> str:
        return str(self.page.url)

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            try:
                self.page.close()
            except PlaywrightError:
                pass

    def __enter__(self) -> PageVisit:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class BrowserSessionManager:
    def __init__(
        self,
        config: BrowserRuntimeConfig,
        *,
        cdp_timeout_ms: int = 20_000,
        navigation_timeout_ms: int = 45_000,
    ) -> None:
        if cdp_timeout_ms <= 0 or navigation_timeout_ms <= 0:
            raise ValueError("Los timeouts deben ser positivos")
        self.config = config
        self.cdp_timeout_ms = cdp_timeout_ms
        self.navigation_timeout_ms = navigation_timeout_ms
        self.runtime: BrowserRuntime | None = None
        self._playwright: Any | None = None
        self._browser: Any | None = None
        self._context: Any | None = None
        self._visits: list[PageVisit] = []

    @property
    def ready(self) -> bool:
        return self.runtime is not None and self._context is not None

    @property
    def cdp_url(self) -> str | None:
        return self.runtime.cdp_url if self.runtime is not None else None

    def start(self) -> BrowserSessionManager:
        if self.ready or self.runtime is not None:
            raise BrowserSessionError("La sesión ya está iniciada")
        try:
            self.runtime = start_browser(self.config)
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.connect_over_cdp(
                self.runtime.cdp_url,
                timeout=self.cdp_timeout_ms,
            )
            if not self._browser.contexts:
                raise BrowserSessionError("CDP no ha expuesto ningún contexto")
            self._context = self._browser.contexts[0]
            return self
        except Exception as exc:
            self.close()
            if isinstance(exc, BrowserSessionError):
                raise
            raise BrowserSessionError(
                f"Falló conexión CDP al navegador externo: {type(exc).__name__}: {exc}"
            ) from exc

    def open_page(self, url: str) -> PageVisit:
        if not self.ready:
            raise BrowserSessionError("Llama a start() antes de navegar")
        assert self._context is not None
        page = self._context.new_page()
        try:
            page.set_default_navigation_timeout(self.navigation_timeout_ms)
            response = page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=self.navigation_timeout_ms,
            )
        except Exception as exc:
            try:
                page.close()
            except Exception:
                pass
            raise BrowserNavigationError(
                f"No se pudo navegar a {url}: {type(exc).__name__}: {exc}"
            ) from exc
        visit = PageVisit(
            page=page,
            requested_url=url,
            response_status=response.status if response is not None else None,
        )
        self._visits.append(visit)
        return visit

    def close(self) -> None:
        for visit in self._visits:
            visit.close()
        self._visits.clear()
        if self._browser is not None:
            try:
                self._browser.close()  # Desconecta CDP; el proceso lo cierra runtime.
            except Exception:
                pass
            self._browser = None
        self._context = None
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:
                pass
            self._playwright = None
        if self.runtime is not None:
            self.runtime.close()
            self.runtime = None

    def __enter__(self) -> BrowserSessionManager:
        return self.start()

    def __exit__(self, *_: object) -> None:
        self.close()
