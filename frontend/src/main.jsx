import React from "react";
import { createRoot } from "react-dom/client";
import {
  BrowserRouter,
  Navigate,
  Route,
  Routes,
  useLocation,
} from "react-router-dom";
import "./tokens.css";
import "./style.css";
import { initTheme } from "./theme";
import { ToastHost } from "./ui";
import Shell, { useSession } from "./shell";
import SignIn from "./screens/signin";
import Today from "./screens/today";
import Decks from "./screens/decks";
import DeckDetail from "./screens/deck";
import Study from "./screens/study";
import Job from "./screens/job";
import Lessons, { DeckLesson } from "./screens/lessons";
import CardsReview from "./screens/cards";
import Leaderboard from "./screens/leaderboard";
import Compare from "./screens/compare";
import You from "./screens/you";

initTheme();

function RequireAuth({ children }) {
  const session = useSession();
  if (session === undefined)
    return <div className="screen"><div className="skeleton" style={{ height: 120 }} /></div>;
  if (!session) return <SignIn />;
  return children;
}

/** The legacy shim: ?job=X links from before real routes existed. */
function Legacy() {
  const location = useLocation();
  const jobId = new URLSearchParams(location.search).get("job");
  return <Navigate to={jobId ? `/job/${jobId}` : "/today"} replace />;
}

function App() {
  return (
    <BrowserRouter>
      <ToastHost>
        <RequireAuth>
          <Routes>
            {/* The tabs, under the shell. */}
            <Route element={<Shell />}>
              <Route path="/today" element={<Today />} />
              <Route path="/decks" element={<Decks />} />
              <Route path="/leaderboard" element={<Leaderboard />} />
              <Route path="/you" element={<You />} />
            </Route>
            {/* Stacks: full-bleed modes, the shell hidden. */}
            <Route path="/deck/:id" element={<DeckDetail />} />
            <Route path="/deck/:id/topic/:topicId" element={<DeckLesson />} />
            <Route path="/study/:deckId" element={<Study />} />
            <Route path="/job/new" element={<Job />} />
            <Route path="/job/:id" element={<Job />} />
            <Route path="/job/:id/lessons" element={<Lessons />} />
            <Route path="/job/:id/cards" element={<CardsReview />} />
            <Route path="/compare/:deckId" element={<Compare />} />
            <Route path="*" element={<Legacy />} />
          </Routes>
        </RequireAuth>
      </ToastHost>
    </BrowserRouter>
  );
}

createRoot(document.getElementById("root")).render(<App />);
