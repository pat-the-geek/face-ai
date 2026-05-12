import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import EntityTimeline from "./EntityTimeline";

// Mock du module api/client — on contrôle ce que renvoie entityTimeline
vi.mock("../api/client", () => ({
  api: {
    entityTimeline: vi.fn(),
  },
}));

import { api } from "../api/client";

function renderWithClient(ui) {
  // Désactive retries pour ne pas attendre en cas d'erreur
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("EntityTimeline", () => {
  it("affiche un loader avant la résolution de la query", () => {
    api.entityTimeline.mockReturnValue(new Promise(() => {})); // jamais résolu
    renderWithClient(<EntityTimeline slug="trump-donald" />);
    expect(screen.getByText(/timeline/i)).toBeInTheDocument();
  });

  it("affiche le message 'pas d'article daté' quand total=0", async () => {
    api.entityTimeline.mockResolvedValue({
      from: "2025-05-11",
      to: "2026-05-11",
      days: [],
      total_articles: 0,
      total_days: 0,
      max_count: 0,
    });
    renderWithClient(<EntityTimeline slug="x" />);
    await waitFor(() =>
      expect(
        screen.getByText(/pas d'article daté sur les 365 derniers jours/i),
      ).toBeInTheDocument(),
    );
  });

  it("rend la heatmap SVG avec les cellules d'activité", async () => {
    api.entityTimeline.mockResolvedValue({
      from: "2026-05-01",
      to: "2026-05-11",
      days: [
        { date: "2026-05-05", count: 3 },
        { date: "2026-05-10", count: 1 },
      ],
      total_articles: 4,
      total_days: 2,
      max_count: 3,
    });
    renderWithClient(<EntityTimeline slug="x" />);
    await waitFor(() =>
      expect(screen.getByText(/activité presse/i)).toBeInTheDocument(),
    );
    // Métadonnées dans le header
    expect(screen.getByText(/4 articles/)).toBeInTheDocument();
    expect(screen.getByText(/2 jours/)).toBeInTheDocument();
    expect(screen.getByText(/pic 3/)).toBeInTheDocument();
    // Le SVG existe
    const svg = document.querySelector("svg[aria-label='Timeline x']");
    expect(svg).toBeTruthy();
  });

  it("appelle onSelectDate au clic sur une cellule active", async () => {
    const onSelectDate = vi.fn();
    api.entityTimeline.mockResolvedValue({
      from: "2026-05-01",
      to: "2026-05-11",
      days: [{ date: "2026-05-05", count: 2 }],
      total_articles: 2,
      total_days: 1,
      max_count: 2,
    });
    renderWithClient(
      <EntityTimeline slug="x" onSelectDate={onSelectDate} />,
    );
    await waitFor(() =>
      expect(screen.getByText(/activité presse/i)).toBeInTheDocument(),
    );
    // Trouve le rect avec count > 0 via son <title>
    const titles = document.querySelectorAll("title");
    const target = Array.from(titles).find((t) =>
      t.textContent.includes("2026-05-05"),
    );
    expect(target).toBeTruthy();
    const rect = target.parentElement;
    const user = userEvent.setup();
    await user.click(rect);
    expect(onSelectDate).toHaveBeenCalledWith("2026-05-05");
  });
});
