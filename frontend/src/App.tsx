import { NavLink, Navigate, Route, Routes } from "react-router-dom";

import { ConnectButton } from "./components/ConnectButton";
import { env, contractConfigured } from "./lib/env";
import Create from "./pages/Create";
import Home from "./pages/Home";
import HowItWorks from "./pages/HowItWorks";
import MarketDetail from "./pages/MarketDetail";
import Portfolio from "./pages/Portfolio";
import ResolveQueue from "./pages/ResolveQueue";

const NAV = [
  { to: "/", label: "Markets", end: true },
  { to: "/create", label: "Create" },
  { to: "/resolve", label: "Resolve queue" },
  { to: "/portfolio", label: "Portfolio" },
  { to: "/how", label: "How it works" },
];

export default function App() {
  return (
    <div className="shell">
      <header className="topbar">
        <NavLink to="/" className="brand" aria-label="Breek Market home">
          <span className="brand-mark" aria-hidden="true">
            B
          </span>
          Breek
        </NavLink>

        <nav className="nav" aria-label="Main">
          {NAV.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.end}>
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="topbar-right">
          <span className="net-pill" title={env.rpc}>
            {env.network} · {env.chainId}
          </span>
          <ConnectButton />
        </div>
      </header>

      <main className="page">
        {!contractConfigured && (
          <div className="notice notice-bad" style={{ marginBottom: 18 }}>
            <strong>No contract configured.</strong> Set <code>VITE_BREEK_CONTRACT</code> to a
            deployed BreekMarket address and reload. Nothing on this page can load until then.
          </div>
        )}

        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/market/:id" element={<MarketDetail />} />
          <Route path="/create" element={<Create />} />
          <Route path="/resolve" element={<ResolveQueue />} />
          <Route path="/portfolio" element={<Portfolio />} />
          <Route path="/how" element={<HowItWorks />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>

      <footer className="foot">
        Breek Market — permissionless GMT+1 prediction markets on GenLayer. Every market
        settles from two independent public feeds fetched by the contract itself. No owner, no
        admin resolve, no oracle.
      </footer>
    </div>
  );
}
