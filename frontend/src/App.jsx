import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, Route, Routes, useLocation } from "react-router-dom";
import AdminPanel from "./components/AdminPanel";
import AlphaNav from "./components/AlphaNav";
import AmbientDebug from "./components/AmbientDebug";
import AuditPanel from "./components/AuditPanel";
import ColorModeToggle from "./components/ColorModeToggle";
import EntityList from "./components/EntityList";
import FontScaler from "./components/FontScaler";
import GalleryPanel from "./components/GalleryPanel";
import GlobalSearch from "./components/GlobalSearch";
import SplitScreen from "./components/SplitScreen";
import { api } from "./api/client";

export default function App() {
  const [letter, setLetter] = useState(null);
  const [favoritesOnly, setFavoritesOnly] = useState(false);
  const location = useLocation();
  const onAuditRoute = location.pathname === "/audit";
  const onAdminRoute = location.pathname === "/admin";
  const onCompareRoute = location.pathname.startsWith("/compare/");
  const fullWidthRoute = onAuditRoute || onAdminRoute || onCompareRoute;

  const { data: flagged } = useQuery({
    queryKey: ["flagged"],
    queryFn: api.flagged,
    refetchInterval: 60_000,
  });
  const flaggedCount = flagged?.total ?? 0;

  return (
    <div className="h-screen flex flex-col">
      <header className="px-8 py-3 border-b divider flex items-baseline justify-between gap-6">
        <Link to="/" className="hover:opacity-80 transition-opacity">
          <span className="font-display-italic text-2xl">FACE.ai</span>
          <span className="ml-3 italic text-xs text-[var(--text-secondary)]">
            portrait automatique de l'espace médiatique
          </span>
        </Link>
        <div className="flex items-center gap-5 text-xs font-mono uppercase tracking-wider">
          <GlobalSearch />
          <FontScaler />
          <ColorModeToggle />
          <Link
            to="/audit"
            className={`transition-colors ${
              onAuditRoute
                ? "text-[var(--accent)]"
                : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
            }`}
          >
            Audit
            {flaggedCount > 0 && (
              <span className="ml-1.5 px-1.5 py-0.5 text-[10px] bg-[var(--accent)] text-white rounded">
                {flaggedCount}
              </span>
            )}
          </Link>
          <Link
            to="/admin"
            className={`transition-colors ${
              onAdminRoute
                ? "text-[var(--accent)]"
                : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
            }`}
          >
            Admin
          </Link>
          <span className="text-[10px] text-[var(--text-secondary)]">v0.0.1</span>
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

      <div
        className={`flex-1 overflow-hidden grid grid-rows-1 ${
          fullWidthRoute
            ? "grid-cols-1"
            : "grid-cols-[fit-content(380px)_1fr]"
        }`}
      >
        {!fullWidthRoute && (
          <aside className="border-r divider overflow-hidden min-h-0 h-full">
            <EntityList letter={letter} favoritesOnly={favoritesOnly} />
          </aside>
        )}
        <main className="overflow-hidden min-h-0">
          <Routes>
            <Route path="/" element={<GalleryPanel />} />
            <Route path="/audit" element={<AuditPanel />} />
            <Route path="/admin" element={<AdminPanel />} />
            <Route
              path="/compare/:slugA/:slugB"
              element={<SplitScreen />}
            />
            <Route path="/:slug" element={<GalleryPanel />} />
          </Routes>
        </main>
      </div>
      <AmbientDebug />
    </div>
  );
}
