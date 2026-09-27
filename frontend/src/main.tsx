import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { Navigate, RouterProvider, createBrowserRouter } from "react-router-dom";
import "./index.css";
import { AppLayout } from "@/components/layout";
import { DashboardView } from "@/features/DashboardView";
import { InspectionView } from "@/features/inspection/InspectionView";
import { StandardsView } from "@/features/StandardsView";
import { StandardLookupView, StandardPassportView } from "@/features/StandardPassportView";
import { ChatView } from "@/features/ChatView";
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
      { path: "chat", element: <ChatView /> },
      // Phase UI-1: one place to ask questions — the old Ask page now lives at /chat.
      { path: "ask", element: <Navigate to="/chat" replace /> },
      { path: "inspection", element: <InspectionView /> },
      { path: "standards", element: <StandardsView /> },
      { path: "standard", element: <StandardLookupView /> },
      { path: "standard/:id", element: <StandardPassportView /> },
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
