import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import {
  CircleMarker,
  MapContainer,
  Marker,
  TileLayer,
  Tooltip,
  useMap,
  useMapEvents,
} from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { api } from "../api/client";

// Au-delà de ce zoom, on affiche la photo + le nom ; en deçà, un simple point
// coloré (vue large = présence, pas de détail lisible).
const PHOTO_ZOOM = 4;
// Plafond de marqueurs-photo rendus simultanément. Sans ça, un zoom sur une
// zone dense (Europe, côte est US) chargerait des centaines d'images externes
// d'un coup et figeait l'onglet. Au-delà, les surnuméraires restent en point.
const MAX_PHOTOS = 200;
const ACCENT = "#c8102e";
const DEFAULT_CENTER = [25, 5];
const DEFAULT_ZOOM = 2;

// Mémorise centre + zoom pour restaurer la carte telle quelle après une
// navigation aller-retour (clic sur une personne → retour). `lastView` (module)
// survit au démontage de MapView dans la session SPA ; sessionStorage assure
// la persistance même après un reload.
const STORAGE_KEY = "face_ai_map_view";
let lastView = null;

function readSavedView() {
  if (lastView) return lastView;
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (raw) return JSON.parse(raw);
  } catch {
    /* navigation privée / storage indispo */
  }
  return null;
}

function saveView(view) {
  lastView = view;
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(view));
  } catch {
    /* navigation privée / storage indispo */
  }
}

// "Chalamet, Timothée" → "Timothée Chalamet" (cohérent avec le mode prénom UI).
function displayName(name) {
  if (name.includes(",")) {
    const [last, first] = name.split(",");
    return `${first.trim()} ${last.trim()}`;
  }
  return name;
}

// Décalage déterministe (±~1.5°) pour les points positionnés au centroïde d'un
// pays : sans ça, toutes les personnes d'une même nationalité se superposent
// exactement. Hash du slug → offset stable entre rendus.
function countryJitter(slug) {
  let h = 0;
  for (let i = 0; i < slug.length; i += 1) {
    h = (h * 31 + slug.charCodeAt(i)) >>> 0;
  }
  const a = ((h % 1000) / 1000 - 0.5) * 3;
  const b = (((h >> 10) % 1000) / 1000 - 0.5) * 3;
  return [a, b];
}

function position(e) {
  if (e.geo_source === "country") {
    const [dLat, dLng] = countryJitter(e.slug);
    return [e.latitude + dLat, e.longitude + dLng];
  }
  return [e.latitude, e.longitude];
}

// DivIcon HTML : vignette ronde + nom. Les classes sont définies dans tokens.css.
// Appelé seulement pour les entités avec `thumbnail_url` (les sans-photo restent
// en point) — pas de branche placeholder.
function photoIcon(e) {
  const safeName = displayName(e.name).replace(/[<>&]/g, "");
  return L.divIcon({
    className: "map-pin-wrapper",
    html: `<div class="map-pin${e.is_favorite ? " map-pin--fav" : ""}"><img src="${e.thumbnail_url}" referrerpolicy="no-referrer" alt="" /><span>${safeName}</span></div>`,
    iconSize: [56, 72],
    iconAnchor: [28, 64],
  });
}

/**
 * Suit zoom + emprise visible. Le culling par viewport est ce qui empêche le
 * gel : on ne rend que les marqueurs réellement à l'écran (avec une marge),
 * pas les ~2000 d'un coup. Émet aussi l'état initial au montage (useMapEvents
 * ne se déclenche pas tout seul au premier rendu).
 */
function MapWatcher({ onChange }) {
  const map = useMap();
  const emit = () => {
    const c = map.getCenter();
    onChange({
      zoom: map.getZoom(),
      center: [c.lat, c.lng],
      bounds: map.getBounds(),
    });
  };
  useEffect(() => {
    emit();
  }, [map]); // eslint-disable-line react-hooks/exhaustive-deps
  useMapEvents({ moveend: emit, zoomend: emit });
  return null;
}

export default function MapView() {
  const navigate = useNavigate();
  // Centre/zoom initiaux restaurés depuis la dernière session de carte (calculé
  // une seule fois). MapContainer ne lit center/zoom qu'au montage — exactement
  // le comportement voulu pour rétablir l'état d'avant le clic.
  const [initial] = useState(() => {
    const saved = readSavedView();
    return {
      center: saved?.center ?? DEFAULT_CENTER,
      zoom: saved?.zoom ?? DEFAULT_ZOOM,
    };
  });
  const [view, setView] = useState({ zoom: initial.zoom, bounds: null });
  const { zoom, bounds } = view;

  // Persiste centre + zoom à chaque déplacement/zoom pour la restauration.
  const handleViewChange = (next) => {
    setView(next);
    if (next.center) saveView({ center: next.center, zoom: next.zoom });
  };

  const { data, isLoading, error } = useQuery({
    queryKey: ["entities-map"],
    queryFn: api.entitiesMap,
    staleTime: 5 * 60_000,
  });

  const entities = useMemo(() => data || [], [data]);
  const showPhotos = zoom >= PHOTO_ZOOM;

  // Position (jittée pour les points-pays) calculée une fois par entité.
  const placed = useMemo(
    () => entities.map((e) => ({ e, pos: position(e) })),
    [entities],
  );

  // Marqueurs visibles dans l'emprise courante (+ marge). Avant la 1re mesure
  // d'emprise, on rend tout (points uniquement, car zoom initial < PHOTO_ZOOM).
  const visible = useMemo(() => {
    if (!bounds) return placed;
    const padded = bounds.pad(0.25);
    return placed.filter(({ pos }) => padded.contains(pos));
  }, [placed, bounds]);

  // Sous-ensemble qui aura une photo : visibles, avec vignette, en zoom photo,
  // plafonné à MAX_PHOTOS. Le reste (et les sans-photo) reste en point.
  const photoSlugs = useMemo(() => {
    if (!showPhotos) return new Set();
    const eligible = visible
      .filter(({ e }) => e.thumbnail_url)
      .slice(0, MAX_PHOTOS);
    return new Set(eligible.map(({ e }) => e.slug));
  }, [visible, showPhotos]);

  return (
    <div className="h-full w-full relative">
      <MapContainer
        center={initial.center}
        zoom={initial.zoom}
        minZoom={2}
        maxZoom={12}
        worldCopyJump
        className="h-full w-full"
        style={{ background: "var(--bg-secondary)" }}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <MapWatcher onChange={handleViewChange} />

        {visible.map(({ e, pos }) => {
          // Photo seulement si éligible (visible, vignette dispo, sous le
          // plafond) ; sinon point coloré — y compris pour les sans-photo.
          if (photoSlugs.has(e.slug)) {
            return (
              <Marker
                key={e.slug}
                position={pos}
                icon={photoIcon(e)}
                eventHandlers={{ click: () => navigate(`/${e.slug}`) }}
              />
            );
          }
          return (
            <CircleMarker
              key={e.slug}
              center={pos}
              radius={5}
              pathOptions={{
                color: e.is_favorite ? "#f0a020" : ACCENT,
                fillColor: e.is_favorite ? "#f0a020" : ACCENT,
                fillOpacity: 0.85,
                weight: 1,
              }}
              eventHandlers={{ click: () => navigate(`/${e.slug}`) }}
            >
              <Tooltip direction="top">{displayName(e.name)}</Tooltip>
            </CircleMarker>
          );
        })}
      </MapContainer>

      <div className="absolute top-3 right-3 z-[1000] px-3 py-2 bg-[var(--bg-primary)]/90 border divider text-[11px] font-mono text-[var(--text-secondary)] pointer-events-none">
        {isLoading
          ? "chargement…"
          : error
            ? `erreur : ${error.message}`
            : `${entities.length} personne${entities.length > 1 ? "s" : ""} géolocalisée${entities.length > 1 ? "s" : ""}`}
        <div className="mt-1 opacity-70">
          {showPhotos ? "zoom : photos" : "zoom : points — zoomez pour les visages"}
        </div>
      </div>
    </div>
  );
}
