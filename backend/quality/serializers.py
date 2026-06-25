from rest_framework import serializers

from .constants import CHECK_SLOTS
from .models import AppSetting, History, InspectionTarget, Job, LayoutMaster, LayoutObject, LayoutObjectType, Machine, MasterClass


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
            "warnings",
            "checks",
        ]

    def get_name(self, obj):
        return obj.master.name if obj.master else obj.normalized_code

    def get_category(self, obj):
        if obj.master is None:
            return None
        mc = MasterClass.objects.filter(master=obj.master).first()
        return mc.class_master.class_no if mc and mc.class_master else None

    def get_class_name(self, obj):
        if obj.master is None:
            return None
        mc = MasterClass.objects.filter(master=obj.master).first()
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
        checked_slots = histories.get(obj.master_id, set()) if obj.master_id else set()
        return {slot: slot in checked_slots for slot in CHECK_SLOTS}


class ManualTargetsRequestSerializer(serializers.Serializer):
    date = serializers.DateField()
    codes = serializers.ListField(
        child=serializers.CharField(max_length=64),
        allow_empty=False,
    )


class CheckItemSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=64)
    checks = serializers.DictField(child=serializers.BooleanField())

    def validate_checks(self, value):
        invalid = set(value) - set(CHECK_SLOTS)
        if invalid:
            raise serializers.ValidationError(f"Invalid time slots: {sorted(invalid)}")
        return {slot: bool(value.get(slot, False)) for slot in CHECK_SLOTS}


class BulkHistoryRequestSerializer(serializers.Serializer):
    date = serializers.DateField()
    items = CheckItemSerializer(many=True, allow_empty=False)


class SingleHistoryRequestSerializer(serializers.Serializer):
    date = serializers.DateField()
    code = serializers.CharField(max_length=64)
    time = serializers.ChoiceField(choices=History.TimeSlot.choices)
    checked = serializers.BooleanField()


class BulkDeleteTargetsRequestSerializer(serializers.Serializer):
    date = serializers.DateField()
    target_ids = serializers.ListField(child=serializers.IntegerField(), allow_empty=False)


class DailyReportGenerateRequestSerializer(serializers.Serializer):
    date = serializers.DateField()


class PlanImportRequestSerializer(serializers.Serializer):
    target_date = serializers.DateField()


class MasterImportRequestSerializer(serializers.Serializer):
    force = serializers.BooleanField(required=False, default=False)


class JobSerializer(serializers.ModelSerializer):
    class Meta:
        model = Job
        fields = [
            "job_id",
            "job_type",
            "status",
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


class LayoutMasterListSerializer(serializers.ModelSerializer):
    class Meta:
        model = LayoutMaster
        fields = ["id", "layout_name", "background_image_path", "grid_width", "grid_height", "created_at", "updated_at"]


class CreateLayoutSerializer(serializers.Serializer):
    layout_name = serializers.CharField(max_length=128)


class MachineSerializer(serializers.ModelSerializer):
    class Meta:
        model = Machine
        fields = ["id", "machine_no", "machine_name"]


class AppSettingSerializer(serializers.ModelSerializer):
    class Meta:
        model = AppSetting
        fields = ["id", "csv_path", "inspection_folder_paths", "erp_path", "updated_at"]
