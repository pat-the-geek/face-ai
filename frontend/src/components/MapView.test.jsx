import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// Leaflet a besoin de mesures DOM réelles (indisponibles en jsdom) : on mocke
// react-leaflet + leaflet pour tester la logique de MapView (fetch, bascule
// points/photos selon le zoom, libellé compteur) sans monter une vraie carte.
vi.mock("react-leaflet", () => {
  // Instance stable (comme le vrai useMap) — sinon le useEffect du MapWatcher
  // boucle à l'infini. Zoom 2 (vue large) + emprise qui contient tout.
  const fakeMap = {
    getZoom: () => 2,
    getCenter: () => ({ lat: 25, lng: 5 }),
    getBounds: () => ({ pad: () => ({ contains: () => true }) }),
  };
  return {
    MapContainer: ({ children }) => <div data-testid="map">{children}</div>,
    TileLayer: () => null,
    Marker: ({ position }) => (
      <div data-testid="photo-marker" data-pos={position.join(",")} />
    ),
    CircleMarker: ({ center, children }) => (
      <div data-testid="dot-marker" data-pos={center.join(",")}>
        {children}
      </div>
    ),
    Tooltip: ({ children }) => <span>{children}</span>,
    useMapEvents: () => null,
    useMap: () => fakeMap,
  };
});

vi.mock("leaflet", () => ({
  default: { divIcon: () => ({}) },
}));

vi.mock("react-router-dom", () => ({
  useNavigate: () => vi.fn(),
}));

const FIXTURE = [
  {
    slug: "marc-andreessen",
    name: "Andreessen, Marc",
    latitude: 42.5,
    longitude: -92.4,
    geo_source: "city",
    thumbnail_url: "/static/aligned/1.jpg",
    image_count: 5,
    is_favorite: false,
  },
  {
    slug: "jean-dupont",
    name: "Dupont, Jean",
    latitude: 46.6,
    longitude: 2.4,
    geo_source: "country",
    thumbnail_url: null,
    image_count: 2,
    is_favorite: true,
  },
];

vi.mock("../api/client", () => ({
  api: { entitiesMap: vi.fn(() => Promise.resolve(FIXTURE)) },
}));

import MapView from "./MapView";

function renderMap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MapView />
    </QueryClientProvider>,
  );
}

describe("MapView", () => {
  it("affiche le compteur de personnes géolocalisées", async () => {
    renderMap();
    await waitFor(() =>
      expect(screen.getByText(/2 personnes géolocalisées/)).toBeInTheDocument(),
    );
  });

  it("rend des points (et non des photos) en vue large", async () => {
    renderMap();
    await waitFor(() =>
      expect(screen.getAllByTestId("dot-marker")).toHaveLength(2),
    );
    expect(screen.queryAllByTestId("photo-marker")).toHaveLength(0);
  });

  it("applique un jitter aux points positionnés par pays", async () => {
    renderMap();
    const dots = await screen.findAllByTestId("dot-marker");
    const country = dots.find((d) =>
      d.getAttribute("data-pos").startsWith("4"),
    );
    // Le point pays (France ~46.6,2.4) est décalé du centroïde exact par le jitter.
    const [lat, lng] = country.getAttribute("data-pos").split(",").map(Number);
    expect(lat).not.toBe(46.6);
    expect(lng).not.toBe(2.4);
  });
});
