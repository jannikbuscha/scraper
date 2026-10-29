// Vitest setup: jest-dom matchers, DOM cleanup, and the browser APIs that
// Mantine expects but jsdom lacks.
import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach, vi } from 'vitest';

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  window.sessionStorage.clear();
});

Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(() => false),
  })),
});

class ResizeObserverStub {
  observe = vi.fn();
  unobserve = vi.fn();
  disconnect = vi.fn();
}
window.ResizeObserver = ResizeObserverStub;

Element.prototype.scrollIntoView = vi.fn();
window.HTMLElement.prototype.scrollTo = vi.fn();
// jsdom has no window.scrollTo; the router calls it on navigation.
window.scrollTo = vi.fn();

// jsdom has no FontFaceSet; Mantine's autosize Textarea listens on it.
Object.defineProperty(document, 'fonts', { configurable: true, value: new EventTarget() });
