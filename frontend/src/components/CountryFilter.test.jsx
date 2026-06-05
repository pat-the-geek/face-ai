import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import CountryFilter from "./CountryFilter";

// Mock du client API : la liste des pays vient de /entities/countries.
vi.mock("../api/client", () => ({
  api: {
    countries: vi.fn(() =>
      Promise.resolve([
        { code: "CH", name: "Suisse", flag: "🇨🇭", count: 142 },
        { code: "FR", name: "France", flag: "🇫🇷", count: 87 },
      ]),
    ),
  },
}));

function renderFilter(props) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <CountryFilter selected={null} onSelect={() => {}} {...props} />
    </QueryClientProvider>,
  );
}

describe("CountryFilter", () => {
  it("rend un chip par pays + le chip Tous, avec drapeau et compteur", async () => {
    renderFilter();
    await waitFor(() => screen.getByText("Suisse"));
    expect(screen.getByText("Tous")).toBeInTheDocument();
    expect(screen.getByText("Suisse")).toBeInTheDocument();
    expect(screen.getByText(/🇫🇷/)).toBeInTheDocument();
    expect(screen.getByText("(142)")).toBeInTheDocument();
  });

  it("appelle onSelect avec le code ISO au clic", async () => {
    const onSelect = vi.fn();
    renderFilter({ onSelect });
    await waitFor(() => screen.getByText("France"));
    fireEvent.click(screen.getByText("France"));
    expect(onSelect).toHaveBeenCalledWith("FR");
  });

  it("désélectionne (null) si on reclique le pays actif", async () => {
    const onSelect = vi.fn();
    renderFilter({ selected: "CH", onSelect });
    await waitFor(() => screen.getByText("Suisse"));
    fireEvent.click(screen.getByText("Suisse"));
    expect(onSelect).toHaveBeenCalledWith(null);
  });

  it("trie les pays par ordre alphabétique (France avant Suisse, malgré l'ordre backend)", async () => {
    // Le mock renvoie CH (142) avant FR (87) — ordre effectif décroissant.
    // L'UI doit réordonner A→Z : France avant Suisse.
    renderFilter();
    await waitFor(() => screen.getByText("Suisse"));
    const labels = screen
      .getAllByRole("button")
      .map((b) => b.textContent)
      .filter((t) => /France|Suisse/.test(t));
    expect(labels.findIndex((t) => /France/.test(t))).toBeLessThan(
      labels.findIndex((t) => /Suisse/.test(t)),
    );
  });

  it("filtre les chips à la saisie, insensible aux accents", async () => {
    renderFilter();
    await waitFor(() => screen.getByText("Suisse"));
    fireEvent.change(screen.getByLabelText("Filtrer les pays"), {
      target: { value: "fra" },
    });
    expect(screen.getByText("France")).toBeInTheDocument();
    expect(screen.queryByText("Suisse")).not.toBeInTheDocument();
  });

  it("Entrée sélectionne le 1er résultat filtré", async () => {
    const onSelect = vi.fn();
    renderFilter({ onSelect });
    await waitFor(() => screen.getByText("Suisse"));
    const input = screen.getByLabelText("Filtrer les pays");
    fireEvent.change(input, { target: { value: "sui" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSelect).toHaveBeenCalledWith("CH");
  });

  it("le chip Tous réinitialise le filtre", async () => {
    const onSelect = vi.fn();
    renderFilter({ selected: "CH", onSelect });
    await waitFor(() => screen.getByText("Tous"));
    fireEvent.click(screen.getByText("Tous"));
    expect(onSelect).toHaveBeenCalledWith(null);
  });
});
