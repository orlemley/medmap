import { Link, NavLink, Outlet } from "react-router";
import { GITHUB_URL } from "../config.js";

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
        <div className="nav-right"><a href={GITHUB_URL}>GitHub</a></div>
      </nav>
      <Outlet />
    </>
  );
}
