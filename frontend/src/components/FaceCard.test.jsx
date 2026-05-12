import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import FaceCard from "./FaceCard";

// FaceCard utilise useMutation (react-query) pour le flag — il faut
// donc l'envelopper dans un QueryClientProvider, même sans intention
// d'appeler la mutation dans les tests.
function renderCard(props) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <FaceCard {...props} />
    </QueryClientProvider>,
  );
}

const baseImage = {
  id: 42,
  source_url: "/static/originals/x.jpg",
  aligned_url: "/static/aligned/x.jpg",
  caption: "Test caption",
  copyright: null,
  association_status: "auto",
  identity_match_score: 0.3,
  face: { pose: "front", yaw: 1.2 },
  article: null,
};

describe("FaceCard — sélection Galton", () => {
  it("n'affiche pas le toggle Galton quand galtonSelectable=false", () => {
    renderCard({ image: baseImage });
    expect(
      screen.queryByRole("button", { name: /pour Galton/i }),
    ).not.toBeInTheDocument();
  });

  it("affiche un ◯ quand galtonSelectable=true et non sélectionnée", () => {
    renderCard({
      image: baseImage,
      galtonSelectable: true,
      galtonSelected: false,
      onToggleGaltonSelect: () => {},
    });
    const btn = screen.getByRole("button", {
      name: /Sélectionner pour Galton/i,
    });
    expect(btn).toHaveTextContent("◯");
    expect(btn).toHaveAttribute("aria-pressed", "false");
  });

  it("affiche un ● quand sélectionnée", () => {
    renderCard({
      image: baseImage,
      galtonSelectable: true,
      galtonSelected: true,
      onToggleGaltonSelect: () => {},
    });
    const btn = screen.getByRole("button", {
      name: /Désélectionner pour Galton/i,
    });
    expect(btn).toHaveTextContent("●");
    expect(btn).toHaveAttribute("aria-pressed", "true");
  });

  it("invoque onToggleGaltonSelect au clic sans déclencher onActivate", async () => {
    const onToggleGaltonSelect = vi.fn();
    const onActivate = vi.fn();
    renderCard({
      image: baseImage,
      onActivate,
      galtonSelectable: true,
      galtonSelected: false,
      onToggleGaltonSelect,
    });
    const user = userEvent.setup();
    await user.click(
      screen.getByRole("button", { name: /Sélectionner pour Galton/i }),
    );
    expect(onToggleGaltonSelect).toHaveBeenCalledTimes(1);
    // Le e.stopPropagation() doit éviter d'ouvrir le Flipbook.
    expect(onActivate).not.toHaveBeenCalled();
  });
});
