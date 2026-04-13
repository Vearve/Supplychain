from django.apps import AppConfig


class SupplChainMngConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'SupplyChain_MNG.SupplChain_MNG'

    def ready(self):
        from . import signals  # noqa: F401
