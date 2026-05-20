from django.urls import path

from .views import (
    BulkHistoryView,
    DailyReportGenerateView,
    FactoryMapView,
    InspectionSheetIssueView,
    InspectionTargetDetailView,
    InspectionTargetsView,
    JobDetailView,
    ManualTargetsView,
    MasterUpdateView,
    PlansImportView,
    SeedMasterView,
    SingleHistoryView,
)


urlpatterns = [
    path("jobs/<str:job_id>/", JobDetailView.as_view()),
    path("master/update/", MasterUpdateView.as_view()),
    path("master/seed/", SeedMasterView.as_view()),
    path("plans/import/", PlansImportView.as_view()),
    path("inspection-targets/", InspectionTargetsView.as_view()),
    path("inspection-targets/manual/", ManualTargetsView.as_view()),
    path("inspection-targets/<int:target_id>/", InspectionTargetDetailView.as_view()),
    path("history/", SingleHistoryView.as_view()),
    path("history/bulk-upsert/", BulkHistoryView.as_view()),
    path("factory-map/", FactoryMapView.as_view()),
    path("inspection-sheet/issue/", InspectionSheetIssueView.as_view()),
    path("daily-report/generate/", DailyReportGenerateView.as_view()),
]
