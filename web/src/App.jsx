import { lazy, Suspense } from "react";
import { BrowserRouter, Link, Navigate, Route, Routes } from "react-router";
import Layout from "./components/Layout.jsx";
import AboutPage from "./pages/AboutPage.jsx";
import HomePage from "./pages/HomePage.jsx";

// MapLibre is ~1 MB, so the map page is its own chunk: Home and About load
// instantly, and the map code downloads only when someone opens the map.
const MapPage = lazy(() => import("./pages/MapPage.jsx"));

function NotFound() {
  return (
    <main className="page">
      <title>MedMap: Not found</title>
      <h1>Page not found</h1>
      <p><Link to="/">Go to the home page</Link></p>
    </main>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<HomePage />} />
          <Route
            path="map"
            element={
              <Suspense fallback={<p className="page-loading">Loading map…</p>}>
                <MapPage />
              </Suspense>
            }
          />
          <Route path="about" element={<AboutPage />} />
          {/* Old links from the plain-HTML version */}
          <Route path="index.html" element={<Navigate to="/" replace />} />
          <Route path="map.html" element={<Navigate to={{ pathname: "/map", search: window.location.search }} replace />} />
          <Route path="about.html" element={<Navigate to="/about" replace />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
