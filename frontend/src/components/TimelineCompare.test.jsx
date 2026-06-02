import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import TimelineCompare from "./TimelineCompare";

// On contrôle la recherche d'entités et la réponse de superposition.
vi.mock("../api/client", () => ({
  api: {
    search: vi.fn(),
    timelineCompare: vi.fn(),
  },
}));

import { api } from "../api/client";

function renderWithClient(ui) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

const COMPARE_RESPONSE = {
  from: "2025-06-01",
  to: "2026-06-01",
  shared_articles: 7,
  a: {
    slug: "sam-altman",
    name: "Altman, Sam",
    days: [
      { date: "2026-01-15", count: 5 },
      { date: "2026-03-10", count: 9 },
    ],
    total_articles: 14,
    max_count: 9,
  },
  b: {
    slug: "elon-musk",
    name: "Musk, Elon",
    days: [
      { date: "2026-02-20", count: 3 },
      { date: "2026-03-12", count: 12 },
    ],
    total_articles: 15,
    max_count: 12,
  },
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe("TimelineCompare", () => {
  it("affiche d'abord le déclencheur '+ comparer'", () => {
    renderWithClient(<TimelineCompare slug="sam-altman" />);
    expect(screen.getByText(/comparer/i)).toBeInTheDocument();
    // Pas encore d'input ni de graphe
    expect(
      document.querySelector('input[placeholder*="superposer"]'),
    ).toBeNull();
  });

  it("ouvre l'input et liste les résultats de recherche (≥2 car.)", async () => {
    api.search.mockResolvedValue({
      results: [
        { id: 1, slug: "elon-musk", name: "Musk, Elon", unique_image_count: 30 },
        // Doit être filtré : c'est l'entité courante
        { id: 2, slug: "sam-altman", name: "Altman, Sam", unique_image_count: 50 },
      ],
    });
    const user = userEvent.setup();
    renderWithClient(<TimelineCompare slug="sam-altman" />);

    await user.click(screen.getByText(/comparer/i));
    const input = document.querySelector('input[placeholder*="superposer"]');
    expect(input).toBeTruthy();

    await user.type(input, "Musk");
    await waitFor(() => expect(api.search).toHaveBeenCalledWith("Musk"));
    await waitFor(() =>
      expect(screen.getByText("Musk, Elon")).toBeInTheDocument(),
    );
    // L'entité courante est exclue du dropdown
    expect(screen.queryByText("Altman, Sam")).toBeNull();
  });

  it("superpose les deux courbes après sélection (2 aires + 2 lignes, articles partagés)", async () => {
    api.search.mockResolvedValue({
      results: [
        { id: 1, slug: "elon-musk", name: "Musk, Elon", unique_image_count: 30 },
      ],
    });
    api.timelineCompare.mockResolvedValue(COMPARE_RESPONSE);
    const user = userEvent.setup();
    renderWithClient(<TimelineCompare slug="sam-altman" />);

    await user.click(screen.getByText(/comparer/i));
    await user.type(
      document.querySelector('input[placeholder*="superposer"]'),
      "Musk",
    );
    await waitFor(() =>
      expect(screen.getByText("Musk, Elon")).toBeInTheDocument(),
    );
    await user.click(screen.getByText("Musk, Elon"));

    await waitFor(() =>
      expect(api.timelineCompare).toHaveBeenCalledWith("sam-altman", "elon-musk"),
    );
    // Le SVG de superposition est rendu avec 2 aires + 2 polylignes
    await waitFor(() => {
      const svg = document.querySelector(
        'svg[aria-label*="Superposition"]',
      );
      expect(svg).toBeTruthy();
      expect(svg.querySelectorAll("polygon")).toHaveLength(2);
      expect(svg.querySelectorAll("polyline")).toHaveLength(2);
    });
    // Articles partagés affichés
    expect(screen.getByText(/7 articles partagés/i)).toBeInTheDocument();
    // Légende : les deux noms (forme naturelle "Prénom Nom")
    expect(screen.getByText(/Sam Altman/)).toBeInTheDocument();
    expect(screen.getByText(/Elon Musk/)).toBeInTheDocument();
  });

  it("'retirer' revient au déclencheur", async () => {
    api.search.mockResolvedValue({
      results: [
        { id: 1, slug: "elon-musk", name: "Musk, Elon", unique_image_count: 30 },
      ],
    });
    api.timelineCompare.mockResolvedValue(COMPARE_RESPONSE);
    const user = userEvent.setup();
    renderWithClient(<TimelineCompare slug="sam-altman" />);

    await user.click(screen.getByText(/comparer/i));
    await user.type(
      document.querySelector('input[placeholder*="superposer"]'),
      "Musk",
    );
    await waitFor(() =>
      expect(screen.getByText("Musk, Elon")).toBeInTheDocument(),
    );
    await user.click(screen.getByText("Musk, Elon"));
    await waitFor(() =>
      expect(
        document.querySelector('svg[aria-label*="Superposition"]'),
      ).toBeTruthy(),
    );

    await user.click(screen.getByText(/retirer/i));
    // Retour au déclencheur, plus de graphe
    expect(screen.getByText(/comparer/i)).toBeInTheDocument();
    expect(
      document.querySelector('svg[aria-label*="Superposition"]'),
    ).toBeNull();
  });
});
