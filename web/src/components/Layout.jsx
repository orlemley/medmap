import { Link, NavLink, Outlet } from "react-router";
import { GITHUB_URL } from "../config.js";
import { useTheme } from "../theme.jsx";

const SUN = (
  <svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true">
    <circle cx="10" cy="10" r="3.6" fill="none" stroke="currentColor" strokeWidth="1.7" />
    <path d="M10 1.8v2.4M10 15.8v2.4M1.8 10h2.4M15.8 10h2.4M4.2 4.2l1.7 1.7M14.1 14.1l1.7 1.7M4.2 15.8l1.7-1.7M14.1 5.9l1.7-1.7"
      stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
  </svg>
);

const MOON = (
  <svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true">
    <path d="M16.5 12.3A7 7 0 0 1 7.7 3.5a7 7 0 1 0 8.8 8.8Z" fill="none" stroke="currentColor"
      strokeWidth="1.7" strokeLinejoin="round" />
  </svg>
);

function ThemeToggle() {
  const { theme, toggleTheme } = useTheme();
  const next = theme === "dark" ? "light" : "dark";
  return (
    <button className="theme-toggle" type="button" onClick={toggleTheme}
      aria-label={`Switch to ${next} mode`} title={`Switch to ${next} mode`}>
      {theme === "dark" ? SUN : MOON}
    </button>
  );
}

export default function Layout() {
  return (
    <>
      <nav className="site-nav" aria-label="Main">
        <Link className="brand" to="/" aria-label="MedMap home">
          <span className="brand-mark" aria-hidden="true">+</span>
          <span className="brand-text">MedMap</span>
        </Link>
        <ul className="nav-links">
          {/* NavLink sets aria-current="page" on the active link */}
          <li><NavLink to="/" end>Home</NavLink></li>
          <li><NavLink to="/map">Map</NavLink></li>
          <li><NavLink to="/about">About</NavLink></li>
        </ul>
        <div className="nav-right">
          <ThemeToggle />
          {/* Opens in a new tab; noopener/noreferrer stop that tab from controlling this one. */}
          <a className="nav-github" href={GITHUB_URL} target="_blank" rel="noopener noreferrer">GitHub</a>
        </div>
      </nav>
      <Outlet />
    </>
  );
}
