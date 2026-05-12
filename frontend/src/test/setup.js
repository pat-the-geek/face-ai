/**
 * Setup global Vitest — appelé une fois avant tous les tests.
 * Étend les matchers Jest avec `@testing-library/jest-dom`
 * (toBeInTheDocument, toHaveClass, etc.) et configure les mocks
 * d'API navigateur utilisés par certains composants.
 */
import "@testing-library/jest-dom/vitest";
import { afterEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";

// Démontage automatique après chaque test pour éviter les fuites entre
// suites (utile en mode watch).
afterEach(() => {
  cleanup();
});

// IntersectionObserver : utilisé par DeferredImg + EntityList sentinel.
// jsdom ne l'implémente pas → mock minimal qui ne fait rien.
class IntersectionObserverMock {
  constructor() {}
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.IntersectionObserver =
  globalThis.IntersectionObserver || IntersectionObserverMock;

// ResizeObserver : peut être utilisé par certaines libs (Virtuoso etc.
// pas chez nous depuis l'abandon, mais on garde le mock par sécurité).
class ResizeObserverMock {
  constructor() {}
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver = globalThis.ResizeObserver || ResizeObserverMock;

// localStorage est dispo dans jsdom, mais on s'assure qu'il est reset
// entre tests (sinon les hooks `useColorMode`, `useSortMode` lisent
// l'état d'un test précédent).
afterEach(() => {
  try {
    localStorage.clear();
  } catch {
    /* peut planter dans certains environnements isolés */
  }
});

// requestIdleCallback (utilisé par useEntitiesProgressive) : jsdom ne
// l'expose pas, on fallback sur setTimeout immédiat pour les tests.
globalThis.requestIdleCallback =
  globalThis.requestIdleCallback ||
  ((cb) => setTimeout(() => cb({ didTimeout: false, timeRemaining: () => 0 }), 0));
globalThis.cancelIdleCallback = globalThis.cancelIdleCallback || clearTimeout;

// Silencieux les warnings React Router connus dans les tests sans Router
// (on wrap dans un MemoryRouter quand nécessaire mais certains tests
// stand-alone n'en ont pas besoin).
const originalError = console.error;
console.error = (...args) => {
  const msg = typeof args[0] === "string" ? args[0] : "";
  if (msg.includes("React Router Future Flag Warning")) return;
  originalError(...args);
};
