from django.contrib import admin

from .models import (
    History,
    InspectionFile,
    InspectionSession,
    InspectionTarget,
    InspectionTargetWarning,
    Job,
    Machine,
    MachineAssignment,
    Master,
    Structure,
)


admin.site.register(History)
admin.site.register(InspectionFile)
admin.site.register(InspectionSession)
admin.site.register(InspectionTarget)
admin.site.register(InspectionTargetWarning)
admin.site.register(Job)
admin.site.register(Machine)
admin.site.register(MachineAssignment)
admin.site.register(Master)
admin.site.register(Structure)
