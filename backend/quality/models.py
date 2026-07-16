from django.db import models
from django.contrib.auth.hashers import check_password, make_password


class User(models.Model):
    class Role(models.TextChoices):
        ADMIN = "admin", "Admin"
        WORKER = "worker", "Worker"

    user_id = models.BigAutoField(primary_key=True)
    login_name = models.CharField(max_length=150, unique=True)
    display_name = models.CharField(max_length=255)
    avatar = models.ImageField(upload_to="avatars/", null=True, blank=True)
    password_hash = models.TextField()
    role = models.CharField(max_length=16, choices=Role.choices)
    is_active = models.BooleanField(default=True)
    last_login = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "users"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(role__in=["admin", "worker"]),
                name="users_role_check",
            )
        ]

    def __str__(self):
        return self.display_name or self.login_name

    @property
    def is_authenticated(self):
        return True

    @property
    def is_anonymous(self):
        return False

    @property
    def is_staff(self):
        return self.role == self.Role.ADMIN and self.is_active

    @property
    def is_superuser(self):
        return self.role == self.Role.ADMIN and self.is_active

    def get_username(self):
        return self.login_name

    def set_password(self, raw_password):
        self.password_hash = make_password(raw_password)

    def check_password(self, raw_password):
        return check_password(raw_password, self.password_hash)

    def has_perm(self, perm, obj=None):
        return self.is_superuser

    def has_module_perms(self, app_label):
        return self.is_superuser


class Master(models.Model):
    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=255)
    node_type = models.CharField(max_length=64, null=True, blank=True)
    node_type_1 = models.CharField(max_length=64, null=True, blank=True)
    node_type_2 = models.CharField(max_length=64, null=True, blank=True)
    department = models.CharField(max_length=128, blank=True)
    category = models.PositiveSmallIntegerField(null=True, blank=True)
    product_category = models.CharField(max_length=128, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["code"])]

    def __str__(self):
        return f"{self.code} {self.name}"


class ClassMaster(models.Model):
    class_no = models.PositiveSmallIntegerField(unique=True)
    class_name = models.CharField(max_length=64)

    def __str__(self):
        return f"{self.class_no}: {self.class_name}"


class MasterClass(models.Model):
    master = models.ForeignKey(Master, on_delete=models.PROTECT, related_name="master_classes")
    class_master = models.ForeignKey(ClassMaster, on_delete=models.PROTECT, null=True, blank=True, related_name="master_classes")
    inspection_sheet_path = models.TextField(blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["master", "class_master"],
                name="unique_master_class",
            )
        ]

    def __str__(self):
        return f"{self.master.code} -> {self.class_master.class_no if self.class_master else '-'}"


class SpecialInspectionClass9(models.Model):
    master = models.OneToOneField(
        Master,
        on_delete=models.PROTECT,
        related_name="special_inspection_class9",
    )
    inspection_sheet_path = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Special Inspection Class 9"
        verbose_name_plural = "Special Inspection Class 9"

    def __str__(self):
        return f"{self.master.code} (class9)"


class AppSetting(models.Model):
    csv_path = models.TextField(blank=True, default="")
    inspection_folder_paths = models.JSONField(default=list, blank=True)
    inspection_folder_priorities = models.JSONField(default=dict, blank=True)
    erp_path = models.TextField(blank=True, default="")
    history_file_path = models.TextField(blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "App Setting"
        verbose_name_plural = "App Settings"


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
    master = models.ForeignKey(Master, on_delete=models.PROTECT, related_name="inspection_files")
    file_name = models.CharField(max_length=255)
    file_path = models.TextField()
    priority = models.IntegerField(default=0)
    file_created = models.DateTimeField(null=True, blank=True)
    discovered_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["file_name"])]


class InspectionSession(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        CLOSED = "closed", "Closed"

    target_date = models.DateField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)
    history = models.BooleanField(default=False)
    note = models.TextField(blank=True, default="")
    owner_user = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name="owned_inspection_sessions")
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name="created_inspection_sessions")
    updated_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name="updated_inspection_sessions")
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name="deleted_inspection_sessions")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["owner_user", "target_date"],
                name="unique_inspection_session_owner_date",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=["open", "closed"]),
                name="inspection_session_status_check",
            )
        ]

    def __str__(self):
        return f"{self.target_date} ({self.status})"


class InspectionTarget(models.Model):
    class RegistrationRoute(models.TextChoices):
        OCR = "ocr", "OCR"
        EXCEL = "excel", "Excel"
        MANUAL_CODE = "manual_code", "Manual code"
        FACTORY_MAP = "factory_map", "Factory map"
        SPECIAL = "special", "Special"
        LEGACY = "legacy", "Legacy"

    class IssueStatus(models.TextChoices):
        NOT_REQUIRED = "not_required", "Not required"
        PENDING = "pending", "Pending"
        ISSUED = "issued", "Issued"
        MISSING_FILE = "missing_file", "Missing file"
        SKIPPED = "skipped", "Skipped"

    session = models.ForeignKey(
        InspectionSession,
        on_delete=models.PROTECT,
        related_name="targets",
    )
    master = models.ForeignKey(
        Master,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="inspection_targets",
    )
    raw_code = models.CharField(max_length=64)
    normalized_code = models.CharField(max_length=32)
    source_ocr = models.BooleanField(default=False)
    source_excel = models.BooleanField(default=False)
    source_manual = models.BooleanField(default=False)
    registration_route = models.CharField(
        max_length=16,
        choices=RegistrationRoute.choices,
        default=RegistrationRoute.LEGACY,
    )
    requires_inspection_sheet = models.BooleanField(default=False)
    issue_status = models.CharField(
        max_length=32,
        choices=IssueStatus.choices,
        default=IssueStatus.NOT_REQUIRED,
    )
    visible = models.BooleanField(default=True)
    class_override = models.PositiveSmallIntegerField(null=True, blank=True)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name="created_inspection_targets")
    updated_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name="updated_inspection_targets")
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name="deleted_inspection_targets")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["session", "normalized_code", "class_override"],
                name="unique_target_per_session_code",
                nulls_distinct=False,
            ),
            models.CheckConstraint(
                condition=models.Q(issue_status__in=["not_required", "pending", "issued", "missing_file", "skipped"]),
                name="inspection_target_issue_status_check",
            ),
            models.CheckConstraint(
                condition=models.Q(class_override__isnull=True) | models.Q(class_override__range=(1, 9)),
                name="inspection_target_class_range_check",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(master__isnull=True)
                    | models.Q(registration_route="legacy")
                    | models.Q(registration_route="special", class_override=9)
                    | models.Q(registration_route="ocr", class_override__in=[1, 2, 3, 4, 5, 8])
                    | models.Q(registration_route="factory_map", class_override__range=(1, 5))
                    | models.Q(registration_route__in=["excel", "manual_code"], class_override__in=[6, 7])
                ),
                name="inspection_target_route_class_check",
            ),
        ]
        indexes = [
            models.Index(fields=["session", "normalized_code"]),
            models.Index(fields=["normalized_code"]),
            models.Index(fields=["master"]),
            models.Index(fields=["session"]),
            models.Index(fields=["issue_status"]),
        ]

    @property
    def display_name(self):
        return self.master.name if self.master else self.normalized_code


class InspectionTargetWarning(models.Model):
    target = models.ForeignKey(
        InspectionTarget,
        on_delete=models.PROTECT,
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

    history_id = models.BigAutoField(primary_key=True, db_column='history_id')
    date = models.DateField()
    master = models.ForeignKey(Master, on_delete=models.PROTECT, related_name="histories")
    time_slot = models.CharField(max_length=1, choices=TimeSlot.choices)
    class_override = models.PositiveSmallIntegerField(null=True, blank=True)
    is_sheet_issued = models.BooleanField(default=False)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name="created_histories")
    updated_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name="updated_histories")
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name="deleted_histories")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["created_by", "date", "master", "time_slot", "class_override"],
                name="unique_history_date_master_slot",
                nulls_distinct=False,
            ),
            models.CheckConstraint(
                condition=models.Q(time_slot__in=["A", "B", "C", "D"]),
                name="history_time_slot_check",
            )
        ]
        indexes = [
            models.Index(fields=["date", "time_slot"]),
            models.Index(fields=["date"]),
            models.Index(fields=["master"]),
            models.Index(fields=["class_override"]),
            models.Index(fields=["date", "class_override"]),
        ]


class Machine(models.Model):
    class ShapeType(models.TextChoices):
        CIRCLE = "circle", "Circle"
        ELLIPSE = "ellipse", "Ellipse"
        RECTANGLE = "rectangle", "Rectangle"

    machine_no = models.CharField(max_length=64, unique=True)
    machine_name = models.CharField(max_length=255)
    machine_class = models.PositiveSmallIntegerField(null=True, blank=True)
    shape_type = models.CharField(max_length=16, choices=ShapeType.choices)
    map_x = models.FloatField()
    map_y = models.FloatField()
    width = models.FloatField()
    height = models.FloatField()
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(machine_class__in=[1, 2, 3, 4, 5, 6, 10]) | models.Q(machine_class__isnull=True),
                name="machine_class_check",
            ),
            models.CheckConstraint(
                condition=models.Q(shape_type__in=["circle", "ellipse", "rectangle"]),
                name="machine_shape_type_check",
            ),
        ]

    def __str__(self):
        return f"{self.machine_no} {self.machine_name}"


class MachineAssignment(models.Model):
    machine = models.ForeignKey(Machine, on_delete=models.PROTECT, related_name="assignments")
    code = models.ForeignKey(Master, to_field="code", on_delete=models.PROTECT, related_name="machine_assignments")
    assignment_class = models.PositiveSmallIntegerField(null=True, blank=True)

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
    owner_user = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name="owned_layouts")
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

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(code__in=["machine", "wall", "path", "area", "stairs", "entrance"]),
                name="layout_object_type_code_check",
            )
        ]

    def __str__(self):
        return self.display_name


class LayoutObject(models.Model):
    layout = models.ForeignKey(LayoutMaster, on_delete=models.PROTECT, related_name="layout_objects")
    object_type = models.ForeignKey(LayoutObjectType, on_delete=models.PROTECT, related_name="layout_objects")
    machine = models.ForeignKey(Machine, on_delete=models.PROTECT, null=True, blank=True, related_name="layout_objects")
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
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name="created_jobs")
    updated_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name="updated_jobs")
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name="deleted_jobs")
    updated_at = models.DateTimeField(auto_now=True, null=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(job_type__in=["master_update", "plans_import", "inspection_sheet_issue", "daily_report_generate"]),
                name="job_type_check",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=["queued", "running", "succeeded", "failed"]),
                name="job_status_check",
            ),
        ]


class UserSetting(models.Model):
    user = models.OneToOneField(User, on_delete=models.PROTECT, primary_key=True, related_name="settings")
    theme = models.CharField(max_length=32, default="light")
    font_size = models.FloatField(default=17.33)
    browser_settings_imported = models.BooleanField(default=False)

    class Meta:
        db_table = "user_settings"


class SystemSetting(models.Model):
    setting_key = models.CharField(max_length=128, primary_key=True)
    setting_value = models.TextField(blank=True, default="")
    updated_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name="updated_system_settings")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "system_settings"


class AuditLog(models.Model):
    log_id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="audit_logs")
    operation = models.CharField(max_length=64)
    table_name = models.CharField(max_length=128)
    record_id = models.CharField(max_length=128)
    logged_at = models.DateTimeField(auto_now_add=True)
    details_json = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "audit_logs"
        indexes = [
            models.Index(fields=["user", "logged_at"]),
            models.Index(fields=["table_name", "record_id"]),
        ]
