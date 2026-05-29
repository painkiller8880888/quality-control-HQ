from django.db import models


class Master(models.Model):
    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=255)
    node_type = models.CharField(max_length=64, null=True, blank=True)
    department = models.CharField(max_length=128, blank=True)
    category = models.PositiveSmallIntegerField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["code"])]

    def __str__(self):
        return f"{self.code} {self.name}"


class Structure(models.Model):
    root_code = models.CharField(max_length=32, db_index=True)
    parent_code = models.CharField(max_length=32, db_index=True)
    child_code = models.CharField(max_length=32, db_index=True)
    level = models.PositiveSmallIntegerField()
    quantity = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["parent_code", "child_code"],
                name="unique_structure_parent_child",
            )
        ]


class InspectionFile(models.Model):
    master = models.ForeignKey(Master, on_delete=models.CASCADE, related_name="inspection_files")
    file_name = models.CharField(max_length=255)
    file_path = models.TextField()
    discovered_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["file_name"])]


class InspectionSession(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        CLOSED = "closed", "Closed"

    target_date = models.DateField(unique=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.target_date} ({self.status})"


class InspectionTarget(models.Model):
    class IssueStatus(models.TextChoices):
        NOT_REQUIRED = "not_required", "Not required"
        PENDING = "pending", "Pending"
        ISSUED = "issued", "Issued"
        MISSING_FILE = "missing_file", "Missing file"
        SKIPPED = "skipped", "Skipped"

    session = models.ForeignKey(
        InspectionSession,
        on_delete=models.CASCADE,
        related_name="targets",
    )
    master = models.ForeignKey(
        Master,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inspection_targets",
    )
    raw_code = models.CharField(max_length=64)
    normalized_code = models.CharField(max_length=32)
    source_ocr = models.BooleanField(default=False)
    source_excel = models.BooleanField(default=False)
    source_manual = models.BooleanField(default=False)
    requires_inspection_sheet = models.BooleanField(default=False)
    issue_status = models.CharField(
        max_length=32,
        choices=IssueStatus.choices,
        default=IssueStatus.NOT_REQUIRED,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["session", "normalized_code"],
                name="unique_target_per_session_code",
            )
        ]
        indexes = [
            models.Index(fields=["session", "normalized_code"]),
            models.Index(fields=["issue_status"]),
        ]

    @property
    def display_name(self):
        return self.master.name if self.master else self.normalized_code


class InspectionTargetWarning(models.Model):
    target = models.ForeignKey(
        InspectionTarget,
        on_delete=models.CASCADE,
        related_name="warnings",
    )
    error_code = models.CharField(max_length=64)
    message = models.TextField()
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class History(models.Model):
    class TimeSlot(models.TextChoices):
        A = "A", "08:30-10:00"
        B = "B", "10:10-12:00"
        C = "C", "12:45-14:45"
        D = "D", "15:00-17:15"

    date = models.DateField()
    master = models.ForeignKey(Master, on_delete=models.CASCADE, related_name="histories")
    time_slot = models.CharField(max_length=1, choices=TimeSlot.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["date", "master", "time_slot"],
                name="unique_history_date_master_slot",
            )
        ]
        indexes = [models.Index(fields=["date", "time_slot"])]


class Machine(models.Model):
    class ShapeType(models.TextChoices):
        CIRCLE = "circle", "Circle"
        ELLIPSE = "ellipse", "Ellipse"
        RECTANGLE = "rectangle", "Rectangle"

    machine_no = models.CharField(max_length=64, unique=True)
    machine_name = models.CharField(max_length=255)
    shape_type = models.CharField(max_length=16, choices=ShapeType.choices)
    map_x = models.FloatField()
    map_y = models.FloatField()
    width = models.FloatField()
    height = models.FloatField()
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.machine_no} {self.machine_name}"


class MachineAssignment(models.Model):
    machine = models.ForeignKey(Machine, on_delete=models.CASCADE, related_name="assignments")
    code = models.ForeignKey(Master, to_field="code", on_delete=models.CASCADE, related_name="machine_assignments")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["machine", "code"],
                name="unique_machine_assignment",
            )
        ]


class LayoutMaster(models.Model):
    layout_name = models.CharField(max_length=128, unique=True)
    background_image_path = models.TextField(blank=True)
    grid_width = models.PositiveIntegerField(default=50)
    grid_height = models.PositiveIntegerField(default=50)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.layout_name


class LayoutObjectType(models.Model):
    code = models.CharField(max_length=32, unique=True)
    display_name = models.CharField(max_length=64)
    color = models.CharField(max_length=32, blank=True)
    image_path = models.TextField(blank=True)
    selectable = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.display_name


class LayoutObject(models.Model):
    layout = models.ForeignKey(LayoutMaster, on_delete=models.CASCADE, related_name="layout_objects")
    object_type = models.ForeignKey(LayoutObjectType, on_delete=models.PROTECT, related_name="layout_objects")
    machine = models.ForeignKey(Machine, on_delete=models.SET_NULL, null=True, blank=True, related_name="layout_objects")
    object_name = models.CharField(max_length=255, blank=True)
    grid_x = models.PositiveIntegerField(default=0)
    grid_y = models.PositiveIntegerField(default=0)
    width = models.PositiveIntegerField(default=1)
    height = models.PositiveIntegerField(default=1)
    rotation = models.FloatField(default=0)
    meta_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["layout", "object_type"], name="quality_lay_layout__41da4b_idx")]

    def __str__(self):
        return self.object_name or self.object_type.code


class Job(models.Model):
    class JobType(models.TextChoices):
        MASTER_UPDATE = "master_update", "Master update"
        PLANS_IMPORT = "plans_import", "Plans import"
        INSPECTION_SHEET_ISSUE = "inspection_sheet_issue", "Inspection sheet issue"
        DAILY_REPORT_GENERATE = "daily_report_generate", "Daily report generate"

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    job_id = models.CharField(max_length=64, primary_key=True)
    job_type = models.CharField(max_length=64, choices=JobType.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    request_payload = models.JSONField(default=dict, blank=True)
    result = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
