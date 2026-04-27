from decimal import Decimal

from django import forms
from django.forms import formset_factory, inlineformset_factory

from .models import (
    AuditLog,
    Category,
    CompanyProfile,
    DeliveryNote,
    DeliveryNoteItem,
    Driver,
    Equipment,
    FleetFuelLog,
    FleetMaintenance,
    GoodsIssue,
    GoodsIssueItem,
    GoodsReceipt,
    GoodsReceiptItem,
    GoodsReturn,
    GoodsReturnItem,
    InventoryBalance,
    InventoryMovement,
    Material,
    MaterialReturn,
    MobileEquipment,
    PPEIssue,
    PPEIssueItem,
    Project,
    Requisition,
    RequisitionItem,
    StoreLocation,
    StorageBin,
    StockTransaction,
    SubCategory,
    UserStoreScope,
)


class DateInput(forms.DateInput):
    input_type = "date"


class DateTimeInput(forms.DateTimeInput):
    input_type = "datetime-local"


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ["name"]


class SubCategoryForm(forms.ModelForm):
    class Meta:
        model = SubCategory
        fields = ["name", "category"]


class EquipmentForm(forms.ModelForm):
    class Meta:
        model = Equipment
        fields = [
            "name",
            "serial_number",
            "subcategory",
            "project",
            "store_location",
            "location",
            "status",
            "purchase_date",
            "service_due_date",
            "photo",
            "document",
            "notes",
            "is_active",
        ]
        widgets = {
            "purchase_date": DateInput(),
            "service_due_date": DateInput(),
        }


class MaterialForm(forms.ModelForm):
    class Meta:
        model = Material
        fields = [
            "name",
            "code_number",
            "part_number",
            "serial_number",
            "is_consumable",
            "measurement_unit",
            "photo",
            "document",
            "category",
            "subcategory",
            "equipment",
            "quantity",
            "unit",
            "min_required",
            "location",
        ]


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ["name", "location", "description"]


class StoreLocationForm(forms.ModelForm):
    class Meta:
        model = StoreLocation
        fields = ["name", "location_type", "project", "is_active"]


class StorageBinForm(forms.ModelForm):
    class Meta:
        model = StorageBin
        fields = ["store_location", "bin_code", "zone", "aisle", "rack", "shelf", "description", "is_active"]


class InventoryBalanceForm(forms.ModelForm):
    class Meta:
        model = InventoryBalance
        fields = ["material", "storage_bin", "on_hand", "reserved"]


class InventoryMovementForm(forms.ModelForm):
    class Meta:
        model = InventoryMovement
        fields = [
            "movement_type",
            "delivery_note",
            "material",
            "quantity",
            "from_store",
            "from_bin",
            "to_store",
            "to_bin",
            "driver",
            "mobile_equipment",
            "reference_type",
            "reference_number",
            "notes",
            "created_by",
        ]


class RequisitionForm(forms.ModelForm):
    class Meta:
        model = Requisition
        fields = [
            "code_number",
            "material",
            "quantity_requested",
            "department",
            "project",
            "requested_by",
            "status",
            "rejection_reason",
            "approved_by",
            "date_requested",
            "fulfilled",
            "notes",
        ]
        widgets = {
            "date_requested": DateTimeInput(),
        }


class MaterialReturnForm(forms.ModelForm):
    class Meta:
        model = MaterialReturn
        fields = [
            "code_number",
            "material",
            "project",
            "quantity_returned",
            "returned_by",
            "date_returned",
            "notes",
        ]
        widgets = {
            "date_returned": DateTimeInput(),
        }


class StockTransactionForm(forms.ModelForm):
    class Meta:
        model = StockTransaction
        fields = [
            "code_number",
            "material",
            "transaction_type",
            "quantity",
            "performed_by",
            "date",
            "notes",
        ]
        widgets = {
            "date": DateTimeInput(),
        }


class DriverForm(forms.ModelForm):
    class Meta:
        model = Driver
        fields = ["full_name", "phone_number", "license_number", "license_expiry", "is_active"]
        widgets = {
            "license_expiry": DateInput(),
        }


class MobileEquipmentForm(forms.ModelForm):
    class Meta:
        model = MobileEquipment
        fields = [
            "name",
            "registration_number",
            "equipment_type",
            "project",
            "store_location",
            "assigned_driver",
            "status",
            "current_location",
            "current_route_from",
            "current_route_to",
            "odometer_reading",
            "service_due_date",
            "road_tax_due_date",
            "fitness_due_date",
            "insurance_due_date",
            "notes",
            "is_active",
        ]
        widgets = {
            "service_due_date": DateInput(),
            "road_tax_due_date": DateInput(),
            "fitness_due_date": DateInput(),
            "insurance_due_date": DateInput(),
        }


class FleetFuelLogForm(forms.ModelForm):
    class Meta:
        model = FleetFuelLog
        fields = [
            "equipment",
            "consumable",
            "fluid_type",
            "quantity",
            "unit",
            "odometer_at_fill",
            "from_location",
            "to_location",
            "logged_by",
            "date_logged",
            "notes",
        ]
        widgets = {
            "date_logged": DateTimeInput(),
        }


class FleetMaintenanceForm(forms.ModelForm):
    class Meta:
        model = FleetMaintenance
        fields = [
            "equipment",
            "maintenance_type",
            "status",
            "start_date",
            "end_date",
            "cost",
            "service_provider",
            "notes",
        ]
        widgets = {
            "start_date": DateInput(),
            "end_date": DateInput(),
        }


class CompanyProfileForm(forms.ModelForm):
    class Meta:
        model = CompanyProfile
        fields = ["company_name", "company_address", "logo"]


class GoodsReceiptForm(forms.ModelForm):
    class Meta:
        model = GoodsReceipt
        fields = [
            "date_received",
            "destination_store",
            "source_type",
            "source_reference",
            "related_delivery_note",
            "prepared_by",
            "delivered_by",
            "received_by",
            "notes",
        ]
        widgets = {
            "date_received": DateInput(),
        }


class GoodsReceiptItemForm(forms.ModelForm):
    class Meta:
        model = GoodsReceiptItem
        fields = ["material", "description", "quantity", "is_returnable"]


class GoodsIssueForm(forms.ModelForm):
    class Meta:
        model = GoodsIssue
        fields = [
            "date_issued",
            "source_store",
            "source_bin",
            "department",
            "issued_to",
            "issued_by",
            "received_by",
            "notes",
        ]
        widgets = {
            "date_issued": DateInput(),
        }


class GoodsIssueItemForm(forms.ModelForm):
    class Meta:
        model = GoodsIssueItem
        fields = ["material", "description", "quantity", "is_returnable", "expected_return_date"]
        widgets = {
            "expected_return_date": DateInput(),
        }


class GoodsReturnForm(forms.ModelForm):
    class Meta:
        model = GoodsReturn
        fields = [
            "date_returned",
            "from_store",
            "destination_store",
            "related_goods_issue",
            "returned_by",
            "received_by",
            "notes",
        ]
        widgets = {
            "date_returned": DateInput(),
        }


class GoodsReturnItemForm(forms.ModelForm):
    class Meta:
        model = GoodsReturnItem
        fields = ["goods_issue_item", "material", "quantity", "condition", "notes"]


class PPEIssueForm(forms.ModelForm):
    class Meta:
        model = PPEIssue
        fields = [
            "date_issued",
            "store_location",
            "source_bin",
            "employee_name",
            "employee_number",
            "department",
            "issue_type",
            "reason",
            "approved_by",
            "issued_by",
            "received_by",
            "notes",
        ]
        widgets = {
            "date_issued": DateInput(),
        }


class PPEIssueItemForm(forms.ModelForm):
    class Meta:
        model = PPEIssueItem
        fields = ["material", "quantity", "size_spec", "notes"]


class UserStoreScopeForm(forms.ModelForm):
    class Meta:
        model = UserStoreScope
        fields = ["user", "store_location", "can_manage"]


class ProjectRequisitionForm(forms.ModelForm):
    """Header form for a multi-material project requisition."""
    class Meta:
        model = Requisition
        fields = ["department", "requested_by", "date_requested", "notes"]
        widgets = {
            "date_requested": DateTimeInput(),
        }


class WorkspaceRequisitionForm(forms.ModelForm):
    """Header form for multi-material requisitions created from the requisitions tab."""
    class Meta:
        model = Requisition
        fields = ["project", "department", "requested_by", "date_requested", "notes"]
        widgets = {
            "date_requested": DateTimeInput(),
        }


class RequisitionItemForm(forms.ModelForm):
    class Meta:
        model = RequisitionItem
        fields = ["material", "quantity_requested", "notes"]


RequisitionItemFormSet = inlineformset_factory(
    Requisition,
    RequisitionItem,
    form=RequisitionItemForm,
    extra=1,
    can_delete=True,
    min_num=1,
    validate_min=True,
)


class DeliveryNoteForm(forms.ModelForm):
    class Meta:
        model = DeliveryNote
        fields = [
            "date_issued",
            "source_requisition",
            "from_location",
            "to_location",
            "prepared_by",
            "delivered_by",
            "received_by",
            "notes",
        ]
        widgets = {
            "date_issued": DateInput(),
        }
        labels = {
            "source_requisition": "Linked Requisition (optional)",
            "from_location": "From Address",
            "to_location": "To Address",
        }


class DeliveryNoteItemForm(forms.ModelForm):
    class Meta:
        model = DeliveryNoteItem
        fields = ["material", "quantity"]


DeliveryNoteItemFormSet = inlineformset_factory(
    DeliveryNote,
    DeliveryNoteItem,
    form=DeliveryNoteItemForm,
    extra=1,
    can_delete=True,
)


GoodsReceiptItemFormSet = inlineformset_factory(
    GoodsReceipt,
    GoodsReceiptItem,
    form=GoodsReceiptItemForm,
    extra=1,
    can_delete=True,
)


GoodsIssueItemFormSet = inlineformset_factory(
    GoodsIssue,
    GoodsIssueItem,
    form=GoodsIssueItemForm,
    extra=1,
    can_delete=True,
)


GoodsReturnItemFormSet = inlineformset_factory(
    GoodsReturn,
    GoodsReturnItem,
    form=GoodsReturnItemForm,
    extra=1,
    can_delete=True,
)


PPEIssueItemFormSet = inlineformset_factory(
    PPEIssue,
    PPEIssueItem,
    form=PPEIssueItemForm,
    extra=1,
    can_delete=True,
)


class InventoryMovementHeaderForm(forms.ModelForm):
    """Header-only form for multi-material inventory movement create (no material/quantity)."""

    class Meta:
        model = InventoryMovement
        fields = [
            "movement_type",
            "delivery_note",
            "from_store",
            "from_bin",
            "to_store",
            "to_bin",
            "driver",
            "mobile_equipment",
            "reference_type",
            "reference_number",
            "notes",
        ]


class MovementItemLine(forms.Form):
    """Single material+quantity row for multi-material inventory movement create."""

    material = forms.ModelChoiceField(
        queryset=Material.objects.all(),
        empty_label="---------",
    )
    quantity = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=Decimal("0.01"),
    )


MovementItemFormSet = formset_factory(
    MovementItemLine,
    extra=1,
    min_num=1,
    validate_min=True,
    can_delete=True,
)
