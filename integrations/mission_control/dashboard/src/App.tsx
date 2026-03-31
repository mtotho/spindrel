import { Routes, Route } from "react-router-dom";
import Shell from "./components/Shell";
import Overview from "./pages/Overview";
import ChannelDetail from "./pages/ChannelDetail";
import Kanban from "./pages/Kanban";
import Activity from "./pages/Activity";

/**
 * Route structure designed for extensibility:
 * - /                        → Global overview
 * - /channels/:id            → Channel detail (files, kanban tab, activity)
 * - /channels/:id/kanban     → Full-page kanban
 * - /activity                → Global activity timeline
 *
 * Future sub-module routes (pluggable):
 * - /bots/:id                → Per-bot dashboard
 * - /users/:id               → Per-user home page
 * - /projects/:id            → Project-level aggregation
 * - /modules/:slug/*         → Dynamic sub-module routing
 */
export default function App() {
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route index element={<Overview />} />
        <Route path="channels/:channelId" element={<ChannelDetail />} />
        <Route path="channels/:channelId/kanban" element={<Kanban />} />
        <Route path="activity" element={<Activity />} />
        {/* Future: per-bot, per-user, per-project routes */}
      </Route>
    </Routes>
  );
}
