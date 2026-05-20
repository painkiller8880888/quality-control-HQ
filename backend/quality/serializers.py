from rest_framework import serializers

from .constants import CHECK_SLOTS
from .models import History, InspectionTarget, Job


class WarningSerializer(serializers.Serializer):
    error_code = serializers.CharField()
    message = serializers.CharField()
    details = serializers.JSONField()


class InspectionTargetSerializer(serializers.ModelSerializer):
    target_id = serializers.IntegerField(source="id", read_only=True)
    code = serializers.CharField(source="normalized_code", read_only=True)
    name = serializers.SerializerMethodField()
    category = serializers.SerializerMethodField()
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
            "source_flags",
            "requires_inspection_sheet",
            "issue_status",
            "warnings",
            "checks",
        ]

    def get_name(self, obj):
        return obj.master.name if obj.master else obj.normalized_code

    def get_category(self, obj):
        return obj.master.category if obj.master else None

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


class DailyReportGenerateRequestSerializer(serializers.Serializer):
    date = serializers.DateField()


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
