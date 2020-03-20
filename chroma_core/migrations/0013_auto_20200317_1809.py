# -*- coding: utf-8 -*-
# Generated by Django 1.11.27 on 2020-03-17 18:09
from __future__ import unicode_literals

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("chroma_core", "0012_ha_json_notify"),
    ]

    operations = [
        migrations.DeleteModel(name="Sample_10",),
        migrations.DeleteModel(name="Sample_300",),
        migrations.DeleteModel(name="Sample_3600",),
        migrations.DeleteModel(name="Sample_60",),
        migrations.DeleteModel(name="Sample_86400",),
        migrations.AlterUniqueTogether(name="series", unique_together=set([]),),
        migrations.RemoveField(model_name="series", name="content_type",),
        migrations.DeleteModel(name="Series",),
    ]
