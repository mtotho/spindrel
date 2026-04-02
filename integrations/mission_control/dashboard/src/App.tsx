import { Routes, Route } from "react-router-dom";
import Shell from "./components/Shell";
import Overview from "./pages/Overview";
import ChannelDetail from "./pages/ChannelDetail";
import Kanban from "./pages/Kanban";
import Journal from "./pages/Journal";
import Timeline from "./pages/Timeline";
import Memory from "./pages/Memory";
import Plans from "./pages/Plans";
import PlanDetail from "./pages/PlanDetail";
import Settings from "./pages/Settings";
import Setup from "./pages/Setup";

export default function App() {
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route index element={<Overview />} />
        <Route path="channels/:channelId" element={<ChannelDetail />} />
{/* Per-channel full-page kanban removed — ChannelDetail has inline kanban tab, /kanban has aggregated view */}
        <Route path="kanban" element={<Kanban />} />
        <Route path="journal" element={<Journal />} />
        <Route path="timeline" element={<Timeline />} />
        <Route path="memory" element={<Memory />} />
        <Route path="plans" element={<Plans />} />
        <Route path="plans/:channelId/:planId" element={<PlanDetail />} />
        <Route path="settings" element={<Settings />} />
        <Route path="setup" element={<Setup />} />
      </Route>
    </Routes>
  );
}
