from django.apps import apps
from django.contrib.auth.models import Group
from django.db.models.signals import post_migrate
from django.dispatch import receiver


@receiver(post_migrate)
def ensure_workspace_groups(sender, **kwargs):
    app_config = apps.get_app_config("SupplChain_MNG")
    if sender != app_config:
        return

    for group_name in ["Operations Manager", "Storekeeper", "Fleet Officer"]:
        Group.objects.get_or_create(name=group_name)
