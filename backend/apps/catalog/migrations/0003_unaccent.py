from django.contrib.postgres.operations import UnaccentExtension
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0002_product_productvariant_and_more"),
    ]

    operations = [
        UnaccentExtension(),
    ]
