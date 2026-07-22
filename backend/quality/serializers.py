import ntpath

from rest_framework import serializers

from .constants import CHECK_SLOTS
from .models import AppSetting, ClassMaster, History, InspectionTarget, Job, LayoutMaster, LayoutObject, LayoutObjectType, Machine, MasterClass
from .services import ClassificationError, resolve_inspection_file, resolve_unambiguous_inspection_file


LAYOUT_OBJECT_TYPES = {"machine", "wall", "path", "area", "stairs", "entrance"}


class WarningSerializer(serializers.Serializer):
    error_code = serializers.CharField()
    message = serializers.CharField()
    details = serializers.JSONField()


class InspectionTargetSerializer(serializers.ModelSerializer):
    target_id = serializers.IntegerField(source="id", read_only=True)
    code = serializers.CharField(source="normalized_code", read_only=True)
    name = serializers.SerializerMethodField()
    category = serializers.SerializerMethodField()
    class_name = serializers.SerializerMethodField()
    product_category = serializers.SerializerMethodField()
    source_flags = serializers.SerializerMethodField()
    checks = serializers.SerializerMethodField()
    warnings = WarningSerializer(many=True, read_only=True)
    has_inspection_file = serializers.SerializerMethodField()

    class Meta:
        model = InspectionTarget
        fields = [
            "target_id",
            "code",
            "name",
            "category",
            "class_name",
            "product_category",
            "source_flags",
            "requires_inspection_sheet",
            "issue_status",
            "visible",
            "warnings",
            "checks",
            "has_inspection_file",
            "class_override",
            "registration_route",
        ]

    def get_name(self, obj):
        return obj.master.name if obj.master else obj.normalized_code

    def get_category(self, obj):
        if obj.class_override:
            return obj.class_override
        if obj.master is None:
            return None
        mc = MasterClass.objects.filter(master=obj.master).exclude(class_master__class_no=9).first()
        return mc.class_master.class_no if mc and mc.class_master else None

    def get_class_name(self, obj):
        if obj.class_override == 9:
            return "特殊検査"
        if obj.class_override:
            class_master = ClassMaster.objects.filter(class_no=obj.class_override).first()
            return class_master.class_name if class_master else None
        if obj.master is None:
            return None
        mc = MasterClass.objects.filter(master=obj.master).exclude(class_master__class_no=9).first()
        return mc.class_master.class_name if mc and mc.class_master else None

    def get_product_category(self, obj):
        return obj.master.product_category if obj.master else None

    def get_source_flags(self, obj):
        return {
            "ocr": obj.source_ocr,
            "excel": obj.source_excel,
            "manual": obj.source_manual,
        }

    def get_checks(self, obj):
        histories = self.context.get("histories", {})
        checked_slots = histories.get((obj.master_id, obj.class_override), set()) if obj.master_id else set()
        return {slot: slot in checked_slots for slot in CHECK_SLOTS}

    def get_has_inspection_file(self, obj):
        if obj.master is None:
            return False
        try:
            resolved = resolve_inspection_file(obj.master, self.get_category(obj))
            if resolved is None and obj.class_override is None:
                resolved = resolve_unambiguous_inspection_file(obj.master)
            return resolved is not None
        except ClassificationError:
            return False


class ManualTargetsRequestSerializer(serializers.Serializer):
    date = serializers.DateField()
    codes = serializers.ListField(
        child=serializers.CharField(max_length=64),
        allow_empty=False,
    )

    def validate(self, attrs):
        if "class_override" in self.initial_data:
            raise serializers.ValidationError({"class_override": "このAPIでは指定できません。"})
        return attrs


class FactoryMapTargetRequestSerializer(serializers.Serializer):
    date = serializers.DateField()
    machine_id = serializers.IntegerField()
    code = serializers.CharField(max_length=64)


class SpecialTargetsRequestSerializer(ManualTargetsRequestSerializer):
    pass


class Class9SettingSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    code = serializers.CharField(max_length=32)
    name = serializers.CharField(read_only=True)
    inspection_sheet_path = serializers.CharField(required=False, allow_blank=True, default="")


class Class9SettingCreateSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=32)
    inspection_sheet_path = serializers.CharField(required=False, allow_blank=True, default="")


class CheckItemSerializer(serializers.Serializer):
    target_id = serializers.IntegerField()
    checks = serializers.DictField(child=serializers.BooleanField())

    def validate_checks(self, value):
        invalid = set(value) - set(CHECK_SLOTS)
        if invalid:
            raise serializers.ValidationError(f"Invalid time slots: {sorted(invalid)}")
        return {slot: bool(value[slot]) for slot in value}


class BulkHistoryRequestSerializer(serializers.Serializer):
    date = serializers.DateField()
    items = CheckItemSerializer(many=True, allow_empty=False)


class SingleHistoryRequestSerializer(serializers.Serializer):
    date = serializers.DateField()
    target_id = serializers.IntegerField()
    time = serializers.ChoiceField(choices=History.TimeSlot.choices)
    checked = serializers.BooleanField()


class BulkHideTargetsRequestSerializer(serializers.Serializer):
    date = serializers.DateField()
    target_ids = serializers.ListField(child=serializers.IntegerField(), allow_empty=False)


class DailyReportGenerateRequestSerializer(serializers.Serializer):
    date = serializers.DateField()


class PlanImportRequestSerializer(serializers.Serializer):
    target_date = serializers.DateField()
    sheet_name = serializers.CharField(required=False, default="")


class MasterImportRequestSerializer(serializers.Serializer):
    force = serializers.BooleanField(required=False, default=False)


class JobSerializer(serializers.ModelSerializer):
    class Meta:
        model = Job
        fields = [
            "job_id",
            "job_type",
            "status",
            "resource_key",
            "blocked_reason",
            "depends_on_id",
            "attempt_count",
            "heartbeat_at",
            "lease_until",
            "worker_id",
            "available_at",
            "started_at",
            "finished_at",
            "error_message",
            "result",
        ]


class LayoutObjectTypeSerializer(serializers.ModelSerializer):
    object_type_id = serializers.IntegerField(source="id", read_only=True)

    class Meta:
        model = LayoutObjectType
        fields = ["object_type_id", "code", "display_name", "color", "image_path", "selectable"]


class LayoutObjectSerializer(serializers.ModelSerializer):
    layout_object_id = serializers.IntegerField(source="id", read_only=True)
    type = serializers.CharField(source="object_type.code", read_only=True)
    machine_id = serializers.IntegerField(source="machine.id", read_only=True, allow_null=True)
    machine_no = serializers.CharField(source="machine.machine_no", read_only=True, allow_null=True)
    machine_name = serializers.CharField(source="machine.machine_name", read_only=True, allow_null=True)

    class Meta:
        model = LayoutObject
        fields = [
            "layout_object_id",
            "type",
            "machine_id",
            "machine_no",
            "machine_name",
            "object_name",
            "grid_x",
            "grid_y",
            "width",
            "height",
            "rotation",
            "meta_json",
        ]


class LayoutObjectInputSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=sorted(LAYOUT_OBJECT_TYPES))
    machine_id = serializers.IntegerField(required=False, allow_null=True)
    object_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    grid_x = serializers.IntegerField(min_value=0)
    grid_y = serializers.IntegerField(min_value=0)
    width = serializers.IntegerField(min_value=1)
    height = serializers.IntegerField(min_value=1)
    rotation = serializers.FloatField(required=False, default=0)
    meta_json = serializers.JSONField(required=False, default=dict)

    def validate_machine_id(self, value):
        if value is not None and not Machine.objects.filter(id=value).exists():
            raise serializers.ValidationError("machine_id does not exist.")
        return value

    def validate(self, attrs):
        if attrs["type"] != "machine":
            attrs["machine_id"] = None
        return attrs


class LayoutSaveRequestSerializer(serializers.Serializer):
    layout_name = serializers.CharField(max_length=128, required=False, default="default")
    background_image_path = serializers.CharField(required=False, allow_blank=True, default="")
    grid_width = serializers.IntegerField(min_value=1, default=50)
    grid_height = serializers.IntegerField(min_value=1, default=50)
    objects = LayoutObjectInputSerializer(many=True, required=False, default=list)

    def validate_background_image_path(self, value):
        return ""


class LayoutMasterListSerializer(serializers.ModelSerializer):
    class Meta:
        model = LayoutMaster
        fields = ["id", "layout_name", "background_image_path", "grid_width", "grid_height", "created_at", "updated_at"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["background_image_path"] = ""
        return data


class CreateLayoutSerializer(serializers.Serializer):
    layout_name = serializers.CharField(max_length=128)


class MachineSerializer(serializers.ModelSerializer):
    class Meta:
        model = Machine
        fields = ["id", "machine_no", "machine_name"]


class MachineDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = Machine
        fields = ["id", "machine_no", "machine_name", "machine_class", "shape_type", "map_x", "map_y", "width", "height", "is_active"]


class MachineAssignmentSerializer(serializers.Serializer):
    code = serializers.CharField()
    name = serializers.CharField()
    assignment_class = serializers.IntegerField(required=False, allow_null=True)


class AssignmentInputSerializer(serializers.Serializer):
    code = serializers.CharField()
    assignment_class = serializers.IntegerField(required=False, allow_null=True, default=None)


class MachineMasterSaveSerializer(serializers.Serializer):
    id = serializers.IntegerField(required=False, allow_null=True)
    machine_no = serializers.CharField(max_length=64)
    machine_name = serializers.CharField(max_length=255)
    machine_class = serializers.IntegerField(required=False, allow_null=True, default=None)
    shape_type = serializers.ChoiceField(choices=["circle", "ellipse", "rectangle"])
    map_x = serializers.FloatField()
    map_y = serializers.FloatField()
    width = serializers.FloatField()
    height = serializers.FloatField()
    is_active = serializers.BooleanField(default=True)
    assignments = serializers.ListField(child=AssignmentInputSerializer(), default=list)


class AppSettingSerializer(serializers.ModelSerializer):
    @staticmethod
    def _folder_path_key(path):
        return ntpath.normcase(ntpath.normpath(path.strip()))

    def validate_inspection_folder_paths(self, value):
        if not isinstance(value, list) or any(not isinstance(path, str) for path in value):
            raise serializers.ValidationError("フォルダパスは文字列の配列で指定してください。")
        normalized_paths = []
        seen = set()
        for path in value:
            trimmed_path = path.strip()
            if not trimmed_path:
                raise serializers.ValidationError("空のフォルダパスは保存できません。")
            comparison_key = self._folder_path_key(trimmed_path)
            if comparison_key in seen:
                raise serializers.ValidationError("同じフォルダパスが複数指定されています。")
            seen.add(comparison_key)
            normalized_paths.append(trimmed_path)
        return normalized_paths

    def validate_inspection_folder_priorities(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("優先順位はフォルダパスをキーにしたオブジェクトで指定してください。")
        normalized_priorities = {}
        seen = set()
        for path, priority in value.items():
            if not isinstance(path, str) or isinstance(priority, bool) or not isinstance(priority, int):
                raise serializers.ValidationError("優先順位は整数で指定してください。")
            trimmed_path = path.strip()
            if not trimmed_path:
                raise serializers.ValidationError("優先順位のフォルダパスは空にできません。")
            comparison_key = self._folder_path_key(trimmed_path)
            if comparison_key in seen:
                raise serializers.ValidationError("優先順位に同じフォルダパスが複数指定されています。")
            seen.add(comparison_key)
            normalized_priorities[trimmed_path] = priority
        return normalized_priorities

    def update(self, instance, validated_data):
        folder_paths = validated_data.get("inspection_folder_paths")
        if folder_paths is None:
            folder_paths = self.validate_inspection_folder_paths(instance.inspection_folder_paths)
            validated_data["inspection_folder_paths"] = folder_paths
        requested_priorities = validated_data.get("inspection_folder_priorities")
        current_priorities = instance.inspection_folder_priorities or {}
        requested_by_key = {
            self._folder_path_key(path): priority
            for path, priority in (requested_priorities or {}).items()
        }
        current_by_key = {
            self._folder_path_key(path): priority
            for path, priority in current_priorities.items()
            if isinstance(path, str) and path.strip()
        }
        validated_data["inspection_folder_priorities"] = {
            path: (
                requested_by_key.get(self._folder_path_key(path), current_by_key.get(self._folder_path_key(path), 0))
                if requested_priorities is not None
                else current_by_key.get(self._folder_path_key(path), 0)
            )
            for path in folder_paths
        }
        return super().update(instance, validated_data)

    class Meta:
        model = AppSetting
        fields = ["id", "csv_path", "inspection_folder_paths", "inspection_folder_priorities", "erp_path", "history_file_path", "updated_at"]
