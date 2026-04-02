import { Routes, Route } from "react-router-dom";
import Shell from "./components/Shell";
import Overview from "./pages/Overview";
import ChannelDetail from "./pages/ChannelDetail";
import Kanban from "./pages/Kanban";
import Activity from "./pages/Activity";
import ComingSoon from "./pages/ComingSoon";

export default function App() {
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route index element={<Overview />} />
        <Route path="channels/:channelId" element={<ChannelDetail />} />
        <Route path="channels/:channelId/kanban" element={<Kanban />} />
        <Route path="activity" element={<Activity />} />
        {/* Catch-all for pages not yet built (timeline, plans, journal, etc.) */}
        <Route path="*" element={<ComingSoon />} />
      </Route>
    </Routes>
  );
}
