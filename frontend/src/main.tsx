import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider, createBrowserRouter } from "react-router-dom";
import "./index.css";
import { AppLayout } from "@/components/layout";
import { DashboardView } from "@/features/DashboardView";
import { InspectionView } from "@/features/inspection/InspectionView";
import { StandardsView } from "@/features/StandardsView";
import { CertificationView } from "@/features/CertificationView";
import { LaboratoriesView } from "@/features/LaboratoriesView";
import { HallmarkingView } from "@/features/HallmarkingView";
import { HistoryView } from "@/features/HistoryView";
import { RecordView } from "@/features/RecordView";
import { NotFoundView } from "@/features/NotFoundView";

const router = createBrowserRouter([
  {
    path: "/",
    element: <AppLayout />,
    children: [
      { index: true, element: <DashboardView /> },
      { path: "inspection", element: <InspectionView /> },
      { path: "standards", element: <StandardsView /> },
      { path: "certification", element: <CertificationView /> },
      { path: "laboratories", element: <LaboratoriesView /> },
      { path: "hallmarking", element: <HallmarkingView /> },
      { path: "history", element: <HistoryView /> },
      { path: "history/:inspectionId", element: <RecordView /> },
      { path: "*", element: <NotFoundView /> },
    ],
  },
]);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>,
);
