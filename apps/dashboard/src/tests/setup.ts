import "@testing-library/jest-dom/vitest";

class TestResizeObserver implements ResizeObserver {
  private readonly callback: ResizeObserverCallback;

  constructor(callback: ResizeObserverCallback) {
    this.callback = callback;
  }

  observe(target: Element) {
    const bounds: DOMRect = {
      x: 0,
      y: 0,
      width: 720,
      height: 300,
      top: 0,
      right: 720,
      bottom: 300,
      left: 0,
      toJSON: () => ({}),
    };
    Object.defineProperty(target, "getBoundingClientRect", {
      configurable: true,
      value: () => bounds,
    });
    Object.defineProperty(target, "clientWidth", { configurable: true, value: 720 });
    Object.defineProperty(target, "clientHeight", { configurable: true, value: 300 });

    queueMicrotask(() => {
      this.callback(
        [{
          target,
          contentRect: { width: 720, height: 300 } as DOMRectReadOnly,
          borderBoxSize: [],
          contentBoxSize: [],
          devicePixelContentBoxSize: [],
        }],
        this,
      );
    });
  }

  unobserve() {}
  disconnect() {}
}

globalThis.ResizeObserver = TestResizeObserver;
