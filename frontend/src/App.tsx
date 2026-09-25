import { NavLink, Navigate, Route, Routes } from "react-router-dom";

import { ConnectButton } from "./components/ConnectButton";
import { WalletPicker } from "./components/WalletPicker";
import { WalletBanner } from "./components/WriteGate";
import { env, contractConfigured } from "./lib/env";
import Board from "./pages/Board";
import HowItWorks from "./pages/HowItWorks";
import MyForecasts from "./pages/MyForecasts";
import OpenRound from "./pages/OpenRound";
import RoundDetail from "./pages/RoundDetail";
import ScoreQueue from "./pages/ScoreQueue";

const NAV = [
  { to: "/", label: "Board", end: true },
  { to: "/open", label: "Open a round" },
  { to: "/score", label: "Score queue" },
  { to: "/me", label: "Your forecasts" },
  { to: "/how", label: "Scoring rule" },
];

export default function App() {
  return (
    <div className="shell">
      <header className="topbar">
        <NavLink to="/" className="brand" aria-label="Breek home">
          breek<em>·</em>
          <small>forecast contest</small>
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
            {env.network}/{env.chainId}
          </span>
          <ConnectButton />
        </div>
      </header>

      <WalletPicker />

      <main className="page">
        <WalletBanner />

        {!contractConfigured && (
          <div className="note note-bad" style={{ marginBottom: 18 }}>
            <strong>No contract configured.</strong> Set{" "}
            <code>VITE_BREEK_CONTRACT</code> to a deployed BreekForecast address
            and reload.
          </div>
        )}

        <Routes>
          <Route path="/" element={<Board />} />
          <Route path="/round/:id" element={<RoundDetail />} />
          <Route path="/open" element={<OpenRound />} />
          <Route path="/score" element={<ScoreQueue />} />
          <Route path="/me" element={<MyForecasts />} />
          <Route path="/how" element={<HowItWorks />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>

      <footer className="foot">
        Breek &mdash; a forecast accuracy contest on GenLayer. Name a price, get
        graded against two independent feeds the contract fetches itself. No
        sides, no owner, no admin scorer.
      </footer>
    </div>
  );
}
