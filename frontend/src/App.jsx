import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, Route, Routes, useLocation } from "react-router-dom";
import AdminPanel from "./components/AdminPanel";
import AlphaNav from "./components/AlphaNav";
import AmbientDebug from "./components/AmbientDebug";
import AuditPanel from "./components/AuditPanel";
import ColorModeToggle from "./components/ColorModeToggle";
import CountryFilter from "./components/CountryFilter";
import EntityList from "./components/EntityList";
import FontScaler from "./components/FontScaler";
import FoulePanel from "./components/FoulePanel";
import GalleryPanel from "./components/GalleryPanel";
import GlobalSearch from "./components/GlobalSearch";
import MapView from "./components/MapView";
import ShareOfVoice from "./components/ShareOfVoice";
import SplitScreen from "./components/SplitScreen";
import { api } from "./api/client";

export default function App() {
  const [letter, setLetter] = useState(null);
  const [favoritesOnly, setFavoritesOnly] = useState(false);
  // Filtre pays partagé (v030) entre la liste et la carte.
  const [country, setCountry] = useState(null);
  const location = useLocation();
  const onAuditRoute = location.pathname === "/audit";
  const onAdminRoute = location.pathname === "/admin";
  const onMapRoute = location.pathname === "/carte";
  const onTrendsRoute = location.pathname === "/tendances";
  const onCompareRoute = location.pathname.startsWith("/compare/");
  const onFouleRoute = location.pathname === "/foule";
  const fullWidthRoute =
    onAuditRoute ||
    onAdminRoute ||
    onMapRoute ||
    onTrendsRoute ||
    onCompareRoute ||
    onFouleRoute;

  const { data: flagged } = useQuery({
    queryKey: ["flagged"],
    queryFn: api.flagged,
    refetchInterval: 60_000,
  });
  const flaggedCount = flagged?.total ?? 0;

  return (
    <div className="h-screen flex flex-col">
      <header className="px-8 py-3 border-b divider flex items-center justify-between gap-6">
        <Link to="/" className="hover:opacity-80 transition-opacity flex flex-col items-start">
          <img
            src="/face_ai_icon.jpg"
            alt="FACE.ai"
            className="w-8 h-8 rounded object-cover mb-1"
          />
          <div>
            <span className="font-display text-2xl">FACE.ai</span>
            <span className="ml-3 italic text-xs text-[var(--text-secondary)]">
              portrait automatique de l'espace médiatique
            </span>
          </div>
        </Link>
        <div className="flex items-center gap-5 text-xs font-mono uppercase tracking-wider">
          <GlobalSearch />
          <FontScaler />
          <ColorModeToggle />
          <Link
            to="/"
            className={`transition-colors ${
              !fullWidthRoute
                ? "text-accent"
                : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
            }`}
          >
            Liste
          </Link>
          <Link
            to="/audit"
            className={`transition-colors ${
              onAuditRoute
                ? "text-accent"
                : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
            }`}
          >
            Audit
            {flaggedCount > 0 && (
              <span className="ml-1.5 px-1.5 py-0.5 text-[10px] bg-accent text-white rounded">
                {flaggedCount}
              </span>
            )}
          </Link>
          <Link
            to="/carte"
            className={`transition-colors ${
              onMapRoute
                ? "text-accent"
                : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
            }`}
          >
            Carte
          </Link>
          <Link
            to="/tendances"
            className={`transition-colors ${
              onTrendsRoute
                ? "text-accent"
                : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
            }`}
          >
            Tendances
          </Link>
          <Link
            to="/foule"
            onClick={() => {
              // Vrai plein écran demandé DANS le geste utilisateur (comme le
              // mode immersif de WUDD) : Safari ne l'accorde qu'ainsi. Desktop only.
              if (typeof window !== "undefined" && window.innerWidth >= 768) {
                document.documentElement.requestFullscreen?.().catch(() => {});
              }
            }}
            className={`transition-colors ${
              onFouleRoute
                ? "text-accent"
                : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
            }`}
          >
            Foule
          </Link>
          <Link
            to="/admin"
            className={`transition-colors ${
              onAdminRoute
                ? "text-accent"
                : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
            }`}
          >
            Admin
          </Link>
          <span className="text-[10px] text-[var(--text-secondary)]">v1.0.0</span>
        </div>
      </header>

      {!fullWidthRoute && (
        <AlphaNav
          active={letter}
          onSelect={setLetter}
          favoritesOnly={favoritesOnly}
          onToggleFavorites={() => setFavoritesOnly((v) => !v)}
        />
      )}

      {/* Filtre pays — visible sur la liste et la carte, état partagé (v030) */}
      {(!fullWidthRoute || onMapRoute) && (
        <CountryFilter selected={country} onSelect={setCountry} />
      )}

      <div
        className={`flex-1 overflow-hidden grid grid-rows-1 ${
          fullWidthRoute
            ? "grid-cols-1"
            : "grid-cols-[fit-content(380px)_1fr]"
        }`}
      >
        {!fullWidthRoute && (
          <aside className="border-r divider overflow-hidden min-h-0 h-full">
            <EntityList
              letter={letter}
              favoritesOnly={favoritesOnly}
              country={country}
            />
          </aside>
        )}
        <main className="overflow-hidden min-h-0">
          <Routes>
            <Route path="/" element={<GalleryPanel />} />
            <Route path="/audit" element={<AuditPanel />} />
            <Route path="/admin" element={<AdminPanel />} />
            <Route path="/carte" element={<MapView country={country} />} />
            <Route path="/tendances" element={<ShareOfVoice />} />
            <Route path="/foule" element={<FoulePanel />} />
            <Route
              path="/compare/:slugA/:slugB"
              element={<SplitScreen />}
            />
            <Route path="/:slug" element={<GalleryPanel />} />
          </Routes>
        </main>
      </div>
      {import.meta.env.DEV && <AmbientDebug />}
    </div>
  );
}
