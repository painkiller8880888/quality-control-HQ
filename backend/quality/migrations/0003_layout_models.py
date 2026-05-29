from django.db import migrations, models
import django.db.models.deletion


def seed_layout_object_types(apps, schema_editor):
    LayoutObjectType = apps.get_model("quality", "LayoutObjectType")
    defaults = [
        ("machine", "機械", "#6366f1"),
        ("wall", "壁", "#64748b"),
        ("path", "通路", "#10b981"),
        ("area", "エリア", "#f59e0b"),
        ("stairs", "階段", "#a855f7"),
        ("entrance", "出入口", "#06b6d4"),
    ]
    for code, display_name, color in defaults:
        LayoutObjectType.objects.get_or_create(
            code=code,
            defaults={
                "display_name": display_name,
                "color": color,
                "selectable": True,
            },
        )


class Migration(migrations.Migration):
    dependencies = [
        ("quality", "0002_alter_master_node_type"),
    ]

    operations = [
        migrations.CreateModel(
            name="LayoutMaster",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("layout_name", models.CharField(max_length=128, unique=True)),
                ("background_image_path", models.TextField(blank=True)),
                ("grid_width", models.PositiveIntegerField(default=50)),
                ("grid_height", models.PositiveIntegerField(default=50)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name="LayoutObjectType",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(max_length=32, unique=True)),
                ("display_name", models.CharField(max_length=64)),
                ("color", models.CharField(blank=True, max_length=32)),
                ("image_path", models.TextField(blank=True)),
                ("selectable", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.CreateModel(
            name="LayoutObject",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("object_name", models.CharField(blank=True, max_length=255)),
                ("grid_x", models.PositiveIntegerField(default=0)),
                ("grid_y", models.PositiveIntegerField(default=0)),
                ("width", models.PositiveIntegerField(default=1)),
                ("height", models.PositiveIntegerField(default=1)),
                ("rotation", models.FloatField(default=0)),
                ("meta_json", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "layout",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="layout_objects", to="quality.layoutmaster"),
                ),
                (
                    "machine",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="layout_objects",
                        to="quality.machine",
                    ),
                ),
                (
                    "object_type",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="layout_objects",
                        to="quality.layoutobjecttype",
                    ),
                ),
            ],
            options={
                "indexes": [models.Index(fields=["layout", "object_type"], name="quality_lay_layout__41da4b_idx")],
            },
        ),
        migrations.RunPython(seed_layout_object_types, migrations.RunPython.noop),
    ]
