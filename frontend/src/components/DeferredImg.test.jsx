import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, act } from "@testing-library/react";
import DeferredImg from "./DeferredImg";

// Mock contrôlable d'IntersectionObserver — capture la callback pour
// pouvoir simuler "l'élément est entré dans le viewport" à la demande.
let lastCallback = null;
const observers = [];

beforeEach(() => {
  lastCallback = null;
  observers.length = 0;
  globalThis.IntersectionObserver = class {
    constructor(cb) {
      lastCallback = cb;
      observers.push(this);
    }
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

function triggerIntersect() {
  act(() => {
    lastCallback?.([{ isIntersecting: true }]);
  });
}

describe("DeferredImg", () => {
  it("affiche le fallback avant intersection", () => {
    render(
      <DeferredImg
        src="/img.jpg"
        alt="portrait"
        fallback={<span data-testid="fb">…</span>}
      />,
    );
    expect(screen.getByTestId("fb")).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("monte l'<img> une fois entré dans le viewport", () => {
    render(<DeferredImg src="/img.jpg" alt="portrait" fallback={<span>fb</span>} />);
    triggerIntersect();
    const img = screen.getByRole("img");
    expect(img).toBeInTheDocument();
    expect(img.getAttribute("src")).toBe("/img.jpg");
    expect(img.getAttribute("alt")).toBe("portrait");
    expect(img.getAttribute("loading")).toBe("lazy");
  });

  it("bascule au fallback si l'image plante (onError)", () => {
    render(
      <DeferredImg
        src="/broken.jpg"
        alt="cassée"
        fallback={<span data-testid="fb">image cassée</span>}
      />,
    );
    triggerIntersect();
    const img = screen.getByRole("img");
    act(() => {
      img.dispatchEvent(new Event("error"));
    });
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByTestId("fb")).toBeInTheDocument();
  });

  it("reset l'état errored quand `src` change", () => {
    const { rerender } = render(
      <DeferredImg
        src="/a.jpg"
        alt="a"
        fallback={<span data-testid="fb">fb</span>}
      />,
    );
    triggerIntersect();
    act(() => {
      screen.getByRole("img").dispatchEvent(new Event("error"));
    });
    expect(screen.queryByRole("img")).not.toBeInTheDocument();

    // Nouvelle src : on doit potentiellement remontrer une image
    rerender(
      <DeferredImg
        src="/b.jpg"
        alt="b"
        fallback={<span data-testid="fb">fb</span>}
      />,
    );
    // shown=true reste, errored=false → img remonte avec la nouvelle src
    const img = screen.getByRole("img");
    expect(img.getAttribute("src")).toBe("/b.jpg");
  });
});
