from django.db import models, transaction
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.utils import timezone
from decimal import Decimal

# Department choices for requisitions
DEPARTMENTS = [
    ('HR', 'HR Department'),
    ('FIN', 'Finance'),
    ('MAINT', 'Maintenance'),
    ('SITE', 'Site Projects'),
    ('SAFETY', 'Safety Department'),
]


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name

class SubCategory(models.Model):
    name = models.CharField(max_length=100)
    category = models.ForeignKey(Category, on_delete=models.CASCADE)
 
    def __str__(self):
        return f"{self.name} ({self.category.name})"

class Equipment(models.Model):
    STATUS_CHOICES = [
        ('ACTIVE', 'Active'),
        ('IN_USE', 'In Use'),
        ('MAINTENANCE', 'Maintenance'),
        ('BROKEN', 'Broken'),
        ('STORED', 'Stored'),
    ]

    name = models.CharField(max_length=100)
    serial_number = models.CharField(max_length=80, unique=True, null=True, blank=True)
    subcategory = models.ForeignKey(SubCategory, on_delete=models.CASCADE)
    project = models.ForeignKey('Project', on_delete=models.SET_NULL, null=True, blank=True)
    store_location = models.ForeignKey('StoreLocation', on_delete=models.SET_NULL, null=True, blank=True, related_name='equipment_items')
    location = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='ACTIVE')
    purchase_date = models.DateField(null=True, blank=True)
    service_due_date = models.DateField(null=True, blank=True)
    photo = models.FileField(upload_to='equipment/photos/', null=True, blank=True)
    document = models.FileField(upload_to='equipment/documents/', null=True, blank=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        serial = f" - {self.serial_number}" if self.serial_number else ""
        return f"{self.name} ({self.subcategory.name}){serial}"

class Material(models.Model):
    MEASUREMENT_UNITS = [
        ('UNIT', 'Units'),
        ('L', 'Litres'),
        ('ML', 'Millilitres'),
        ('G', 'Grams'),
        ('KG', 'Kilograms'),
        ('TON', 'Tonnes'),
    ]

    name = models.CharField(max_length=100)
    code_number = models.CharField(max_length=50, unique=True, default='UNKNOWN')  # Add unique=True
    part_number = models.CharField(max_length=50, unique=True, null=True, blank=True)  # Optional
    serial_number = models.CharField(max_length=80, blank=True)
    is_consumable = models.BooleanField(default=False)
    measurement_unit = models.CharField(max_length=8, choices=MEASUREMENT_UNITS, default='UNIT')
    photo = models.FileField(upload_to='materials/photos/', null=True, blank=True)
    document = models.FileField(upload_to='materials/documents/', null=True, blank=True)
    category = models.ForeignKey(Category, on_delete=models.CASCADE)
    subcategory = models.ForeignKey(SubCategory, on_delete=models.SET_NULL, null=True, blank=True)
    equipment = models.ForeignKey(Equipment, on_delete=models.SET_NULL, null=True, blank=True)
    quantity = models.PositiveIntegerField(default=0)
    unit = models.CharField(max_length=20)  # e.g., liters, kg, units
    min_required = models.PositiveIntegerField(default=0)
    location = models.CharField(max_length=100, blank=True)

    def __str__(self):
        return f"{self.name} [{self.code_number}]"

    def needs_restock(self):
        return self.quantity <= self.min_required


class StockTransaction(models.Model):
    code_number = models.CharField(max_length=50, default='UNKNOWN')
    material = models.ForeignKey(Material, on_delete=models.CASCADE, null=True, blank=True)
    TRANSACTION_TYPE = [
        ('IN', 'Stock In'),
        ('OUT', 'Stock Out'),
    ]
    transaction_type = models.CharField(max_length=3, choices=TRANSACTION_TYPE)
    quantity = models.PositiveIntegerField()
    performed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    date = models.DateTimeField(default=timezone.now)
    notes = models.TextField(blank=True)

    def save(self, *args, **kwargs):
        if self.code_number:
            try:
                self.material = Material.objects.get(code_number=self.code_number)
            except Material.DoesNotExist:
                self.material = None
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.get_transaction_type_display()} {self.quantity} of {self.material.name if self.material else 'Unknown'}"

    @property
    def code_number_display(self):
        return self.material.code_number if self.material else self.code_number


class Project(models.Model):
    name = models.CharField(max_length=100, unique=True)
    location = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)

    def __str__(self):
        return self.name


class Warehouse(models.Model):
    name = models.CharField(max_length=120, unique=True)
    location = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class StoreLocation(models.Model):
    LOCATION_TYPE_CHOICES = [
        ("HQ", "Main Warehouse"),
        ("SITE", "Site Store"),
        ("SCRAP", "Scrap Yard"),
        ("SUPPLIER", "Supplier Transit"),
    ]

    name = models.CharField(max_length=120, unique=True)
    location_type = models.CharField(max_length=12, choices=LOCATION_TYPE_CHOICES, default="SITE")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.SET_NULL, null=True, blank=True, related_name="store_locations")
    project = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True, blank=True, related_name="store_locations")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def clean(self):
        errors = {}
        if self.location_type in {"HQ", "SITE"} and not self.warehouse_id:
            errors["warehouse"] = "Warehouse is required for HQ and Site stores."
        if self.location_type == "SITE" and not self.project_id:
            errors["project"] = "Project/Site is required when location type is SITE."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return self.name


class StorageBin(models.Model):
    store_location = models.ForeignKey(StoreLocation, on_delete=models.CASCADE, related_name="bins")
    bin_code = models.CharField(max_length=3)
    zone = models.CharField(max_length=40, blank=True)
    aisle = models.CharField(max_length=40, blank=True)
    rack = models.CharField(max_length=40, blank=True)
    shelf = models.CharField(max_length=40, blank=True)
    description = models.CharField(max_length=180, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["store_location", "bin_code"], name="unique_bin_per_store"),
        ]
        ordering = ["store_location__name", "bin_code"]

    def save(self, *args, **kwargs):
        if not self.bin_code:
            used_numbers = {
                int(code)
                for code in StorageBin.objects.filter(store_location=self.store_location).values_list("bin_code", flat=True)
                if code and code.isdigit()
            }
            for number in range(1, 1000):
                if number not in used_numbers:
                    self.bin_code = f"{number:03d}"
                    break
            if not self.bin_code:
                raise ValidationError("No available numeric bin codes left in this store (001-999).")

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.store_location.name} / BIN {self.bin_code}"


class InventoryBalance(models.Model):
    material = models.ForeignKey(Material, on_delete=models.CASCADE, related_name="inventory_balances")
    storage_bin = models.ForeignKey(StorageBin, on_delete=models.CASCADE, related_name="inventory_balances")
    on_hand = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    reserved = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    min_required = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text="Minimum stock threshold for this material in this warehouse bin.")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["material", "storage_bin"], name="unique_material_balance_per_bin"),
        ]
        ordering = ["material__name", "storage_bin__store_location__name", "storage_bin__bin_code"]

    def __str__(self):
        return f"{self.material.name} @ {self.storage_bin}"


class InventoryMovement(models.Model):
    MOVEMENT_TYPES = [
        ("RECEIPT", "Receipt"),
        ("ISSUE", "Issue"),
        ("TRANSFER", "Transfer"),
        ("RETURN", "Return"),
        ("ADJUSTMENT", "Adjustment"),
    ]

    movement_type = models.CharField(max_length=12, choices=MOVEMENT_TYPES)
    material = models.ForeignKey(Material, on_delete=models.PROTECT, related_name="inventory_movements")
    quantity = models.DecimalField(max_digits=12, decimal_places=2)

    from_store = models.ForeignKey(StoreLocation, on_delete=models.SET_NULL, null=True, blank=True, related_name="movements_out")
    from_bin = models.ForeignKey(StorageBin, on_delete=models.SET_NULL, null=True, blank=True, related_name="movements_out")
    to_store = models.ForeignKey(StoreLocation, on_delete=models.SET_NULL, null=True, blank=True, related_name="movements_in")
    to_bin = models.ForeignKey(StorageBin, on_delete=models.SET_NULL, null=True, blank=True, related_name="movements_in")

    reference_type = models.CharField(max_length=40, blank=True)
    reference_number = models.CharField(max_length=60, blank=True)
    notes = models.TextField(blank=True)
    
    # Optional tracking fields for fleet operations
    delivery_note = models.ForeignKey('DeliveryNote', on_delete=models.SET_NULL, null=True, blank=True, related_name="inventory_movements")
    driver = models.ForeignKey('Driver', on_delete=models.SET_NULL, null=True, blank=True, related_name="inventory_movements")
    mobile_equipment = models.ForeignKey('MobileEquipment', on_delete=models.SET_NULL, null=True, blank=True, related_name="inventory_movements")
    
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def clean(self):
        errors = {}

        if self.quantity is None or self.quantity <= 0:
            errors["quantity"] = "Quantity must be greater than zero."

        if self.from_bin and self.from_store and self.from_bin.store_location_id != self.from_store_id:
            errors["from_bin"] = "From BIN must belong to selected From Store."
        if self.to_bin and self.to_store and self.to_bin.store_location_id != self.to_store_id:
            errors["to_bin"] = "To BIN must belong to selected To Store."

        if self.movement_type == "RECEIPT" and not self.to_bin:
            errors["to_bin"] = "Receipt movement requires To BIN."
        if self.movement_type == "ISSUE" and not self.from_bin:
            errors["from_bin"] = "Issue movement requires From BIN."
        if self.movement_type == "TRANSFER" and (not self.from_bin or not self.to_bin):
            errors["to_bin"] = "Transfer movement requires both From BIN and To BIN."
        if self.movement_type == "RETURN" and not self.to_bin:
            errors["to_bin"] = "Return movement requires To BIN."
        if self.movement_type == "ADJUSTMENT" and not self.from_bin and not self.to_bin:
            errors["to_bin"] = "Adjustment movement requires at least one BIN (From or To)."

        if self.from_bin and self.to_bin and self.from_bin_id == self.to_bin_id:
            errors["to_bin"] = "From BIN and To BIN cannot be the same."

        if errors:
            raise ValidationError(errors)

    def _effects(self):
        qty = self.quantity
        if self.movement_type == "RECEIPT":
            return [(self.to_bin, qty)]
        if self.movement_type == "ISSUE":
            return [(self.from_bin, -qty)]
        if self.movement_type == "TRANSFER":
            return [(self.from_bin, -qty), (self.to_bin, qty)]
        if self.movement_type == "RETURN":
            return [(self.to_bin, qty)]

        effects = []
        if self.from_bin:
            effects.append((self.from_bin, -qty))
        if self.to_bin:
            effects.append((self.to_bin, qty))
        return effects

    @staticmethod
    def _apply_delta(material, storage_bin, delta):
        if not storage_bin or not delta:
            return

        balance, _ = InventoryBalance.objects.get_or_create(
            material=material,
            storage_bin=storage_bin,
            defaults={"on_hand": 0, "reserved": 0},
        )
        new_on_hand = balance.on_hand + delta
        if new_on_hand < 0:
            raise ValidationError(
                f"Insufficient stock for {material.name} in {storage_bin}. Available: {balance.on_hand}, requested: {abs(delta)}"
            )

        balance.on_hand = new_on_hand
        if balance.reserved > balance.on_hand:
            balance.reserved = balance.on_hand
        balance.save(update_fields=["on_hand", "reserved", "updated_at"])

    def _apply_movement(self, direction=1):
        for storage_bin, delta in self._effects():
            self._apply_delta(self.material, storage_bin, delta * direction)

    def save(self, *args, **kwargs):
        self.full_clean()

        if self.from_bin and not self.from_store_id:
            self.from_store = self.from_bin.store_location
        if self.to_bin and not self.to_store_id:
            self.to_store = self.to_bin.store_location

        with transaction.atomic():
            old_movement = None
            if self.pk:
                old_movement = InventoryMovement.objects.select_for_update().get(pk=self.pk)
                old_movement._apply_movement(direction=-1)

            super().save(*args, **kwargs)
            self._apply_movement(direction=1)

    def delete(self, *args, **kwargs):
        with transaction.atomic():
            self._apply_movement(direction=-1)
            super().delete(*args, **kwargs)

    def __str__(self):
        return f"{self.movement_type} {self.quantity} {self.material.name}"

class Requisition(models.Model):
    STATUS_CHOICES = [
        ("DRAFT", "Draft"),
        ("SUBMITTED", "Submitted"),
        ("VALIDATED", "Validated"),
        ("APPROVED", "Approved"),
        ("REJECTED", "Rejected"),
        ("FULFILLED", "Fulfilled"),
    ]

    req_number = models.CharField(max_length=24, unique=True, blank=True)
    code_number = models.CharField(max_length=50, default='UNKNOWN')
    material = models.ForeignKey(Material, on_delete=models.CASCADE, null=True, blank=True)
    quantity_requested = models.PositiveIntegerField(default=0)
    department = models.CharField(max_length=10, choices=DEPARTMENTS)
    project = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True, blank=True)  # New field
    requested_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='requested_by')
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_by')
    date_requested = models.DateTimeField(default=timezone.now)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default="DRAFT")
    submitted_at = models.DateTimeField(null=True, blank=True)
    validated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='validated_requisitions')
    validated_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='rejected_requisitions')
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)
    reserved_quantity = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    fulfilled = models.BooleanField(default=False)
    notes = models.TextField(blank=True)

    def _generate_req_number(self):
        stamp = timezone.localdate().strftime("%y%m")
        prefix = f"REQ-{stamp}-"
        last = Requisition.objects.filter(req_number__startswith=prefix).order_by("-req_number").first()
        seq = 1
        if last:
            try:
                seq = int(last.req_number.split("-")[-1]) + 1
            except Exception:
                seq = 1
        return f"{prefix}{seq:04d}"

    def save(self, *args, **kwargs):
        if not self.req_number:
            self.req_number = self._generate_req_number()
        if self.code_number and self.code_number != 'UNKNOWN':
            try:
                self.material = Material.objects.get(code_number=self.code_number)
            except Material.DoesNotExist:
                self.material = None
        if self.status == "FULFILLED":
            self.fulfilled = True
        elif self.status in {"DRAFT", "SUBMITTED", "VALIDATED", "APPROVED", "REJECTED"}:
            self.fulfilled = False
        super().save(*args, **kwargs)

    def __str__(self):
        return self.req_number or f"REQ-{self.pk}"

    @property
    def code_number_display(self):
        return self.material.code_number if self.material else self.code_number


class RequisitionReservation(models.Model):
    requisition = models.ForeignKey(Requisition, on_delete=models.CASCADE, related_name="reservations")
    inventory_balance = models.ForeignKey(InventoryBalance, on_delete=models.CASCADE, related_name="requisition_reservations")
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["requisition", "inventory_balance"], name="unique_requisition_reservation_line"),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.requisition_id} -> {self.inventory_balance_id} ({self.quantity})"


class RequisitionReadReceipt(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='requisition_read_receipts')
    requisition = models.ForeignKey(Requisition, on_delete=models.CASCADE, related_name='read_receipts')
    read_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'requisition'], name='unique_requisition_read_receipt'),
        ]
        ordering = ['-read_at']

    def __str__(self):
        return f"{self.user.username} read requisition {self.requisition_id}"


class RequisitionItem(models.Model):
    requisition = models.ForeignKey(Requisition, on_delete=models.CASCADE, related_name="items")
    material = models.ForeignKey(Material, on_delete=models.PROTECT)
    quantity_requested = models.DecimalField(max_digits=12, decimal_places=2)
    notes = models.CharField(max_length=220, blank=True)

    class Meta:
        ordering = ["material__name"]

    def __str__(self):
        return f"{self.material.name} x {self.quantity_requested}"


class MaterialReturn(models.Model):
    code_number = models.CharField(max_length=50, default='UNKNOWN')  # Add code_number field
    material = models.ForeignKey(Material, on_delete=models.CASCADE, null=True, blank=True)
    project = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True, blank=True)
    quantity_returned = models.PositiveIntegerField()
    returned_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    date_returned = models.DateTimeField(default=timezone.now)
    notes = models.TextField(blank=True)

    def save(self, *args, **kwargs):
        if self.code_number:
            try:
                self.material = Material.objects.get(code_number=self.code_number)
            except Material.DoesNotExist:
                self.material = None
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.quantity_returned} {self.material.unit if self.material else ''} of {self.material.name if self.material else 'Unknown'} returned from {self.project.name if self.project else 'Unknown Project'}"

    @property
    def code_number_display(self):
        return self.material.code_number if self.material else self.code_number


class Driver(models.Model):
    full_name = models.CharField(max_length=120)
    phone_number = models.CharField(max_length=30, blank=True)
    license_number = models.CharField(max_length=60, unique=True)
    license_expiry = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.full_name


class MobileEquipment(models.Model):
    STATUS_CHOICES = [
        ('ACTIVE', 'Active'),
        ('BREAKDOWN', 'Breakdown'),
        ('REPAIRING', 'Repairing'),
        ('SERVICED', 'Serviced'),
        ('PARKED', 'Parked'),
    ]

    name = models.CharField(max_length=120)
    registration_number = models.CharField(max_length=60, unique=True)
    equipment_type = models.CharField(max_length=80)
    project = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True, blank=True)
    store_location = models.ForeignKey(StoreLocation, on_delete=models.SET_NULL, null=True, blank=True, related_name='mobile_equipment_items')
    assigned_driver = models.ForeignKey(Driver, on_delete=models.SET_NULL, null=True, blank=True)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='ACTIVE')
    current_location = models.CharField(max_length=200, blank=True)
    current_route_from = models.CharField(max_length=120, blank=True)
    current_route_to = models.CharField(max_length=120, blank=True)
    odometer_reading = models.PositiveIntegerField(default=0)

    service_due_date = models.DateField(null=True, blank=True)
    road_tax_due_date = models.DateField(null=True, blank=True)
    fitness_due_date = models.DateField(null=True, blank=True)
    insurance_due_date = models.DateField(null=True, blank=True)

    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name} ({self.registration_number})"


class FleetFuelLog(models.Model):
    FLUID_CHOICES = [
        ('FUEL', 'Fuel'),
        ('OIL', 'Oil'),
        ('GREASE', 'Grease'),
    ]

    equipment = models.ForeignKey(MobileEquipment, on_delete=models.CASCADE)
    consumable = models.ForeignKey(Material, on_delete=models.SET_NULL, null=True, blank=True)
    fluid_type = models.CharField(max_length=10, choices=FLUID_CHOICES, default='FUEL')
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    unit = models.CharField(max_length=8, choices=Material.MEASUREMENT_UNITS, default='L')
    odometer_at_fill = models.PositiveIntegerField(default=0)
    from_location = models.CharField(max_length=120, blank=True)
    to_location = models.CharField(max_length=120, blank=True)
    logged_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    date_logged = models.DateTimeField(default=timezone.now)
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"{self.equipment} - {self.fluid_type} {self.quantity}{self.unit}"


class FleetMaintenance(models.Model):
    MAINTENANCE_CHOICES = [
        ('SERVICE', 'Service'),
        ('REPAIR', 'Repair'),
        ('BREAKDOWN', 'Breakdown'),
        ('FITNESS', 'Fitness Check'),
    ]
    STATUS_CHOICES = [
        ('OPEN', 'Open'),
        ('CLOSED', 'Closed'),
    ]

    equipment = models.ForeignKey(MobileEquipment, on_delete=models.CASCADE)
    maintenance_type = models.CharField(max_length=12, choices=MAINTENANCE_CHOICES, default='SERVICE')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='OPEN')
    start_date = models.DateField(default=timezone.now)
    end_date = models.DateField(null=True, blank=True)
    cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    service_provider = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"{self.equipment} - {self.get_maintenance_type_display()}"


class CompanyProfile(models.Model):
    company_name = models.CharField(max_length=150, default="Leos Investments Ltd")
    company_address = models.TextField(blank=True)
    logo = models.FileField(upload_to="company/logo/", null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.company_name


class DeliveryNote(models.Model):
    STATUS_CHOICES = [
        ("DRAFT", "Draft"),
        ("APPROVED", "Approved"),
        ("DISPATCHED", "Dispatched"),
        ("RECEIVED", "Received"),
        ("CANCELLED", "Cancelled"),
    ]

    note_number = models.CharField(max_length=20, unique=True, blank=True)
    date_issued = models.DateField(default=timezone.localdate)

    company_name = models.CharField(max_length=150, blank=True)
    company_address = models.TextField(blank=True)
    company_logo = models.FileField(upload_to="delivery_notes/logo/", null=True, blank=True)

    from_location = models.CharField(max_length=150)
    to_location = models.CharField(max_length=150)

    prepared_by = models.CharField(max_length=120)
    delivered_by = models.CharField(max_length=120)
    received_by = models.CharField(max_length=120)

    source_requisition = models.ForeignKey(
        Requisition,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="delivery_notes",
    )
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default="DRAFT")
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="delivery_notes_approved")
    approved_at = models.DateTimeField(null=True, blank=True)
    dispatched_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="delivery_notes_dispatched")
    dispatched_at = models.DateTimeField(null=True, blank=True)
    received_by_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="delivery_notes_received")
    received_at = models.DateTimeField(null=True, blank=True)
    stock_posted = models.BooleanField(default=False)

    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="delivery_notes_created")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def _generate_note_number(self):
        # Format: DN-YYMM-####
        stamp = timezone.localdate().strftime("%y%m")
        prefix = f"DN-{stamp}-"
        last_note = DeliveryNote.objects.filter(note_number__startswith=prefix).order_by("-note_number").first()
        if not last_note:
            seq = 1
        else:
            try:
                seq = int(last_note.note_number.split("-")[-1]) + 1
            except Exception:
                seq = 1
        return f"{prefix}{seq:04d}"

    def save(self, *args, **kwargs):
        if not self.note_number:
            self.note_number = self._generate_note_number()

        if not self.company_name or not self.company_address:
            profile = CompanyProfile.objects.first()
            if profile:
                self.company_name = self.company_name or profile.company_name
                self.company_address = self.company_address or profile.company_address
                if not self.company_logo and profile.logo:
                    self.company_logo = profile.logo

        super().save(*args, **kwargs)

    def __str__(self):
        return self.note_number


class DeliveryNoteItem(models.Model):
    delivery_note = models.ForeignKey(DeliveryNote, on_delete=models.CASCADE, related_name="items")
    material = models.ForeignKey(Material, on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=12, decimal_places=2)

    def __str__(self):
        return f"{self.material.name} x {self.quantity}"


class GoodsReceipt(models.Model):
    STATUS_CHOICES = [
        ("DRAFT", "Draft"),
        ("POSTED", "Posted"),
        ("CANCELLED", "Cancelled"),
    ]
    SOURCE_CHOICES = [
        ("HQ", "HQ Transfer"),
        ("SUPPLIER", "Supplier Delivery"),
        ("SITE", "Site Transfer"),
    ]

    receipt_number = models.CharField(max_length=24, unique=True, blank=True)
    date_received = models.DateField(default=timezone.localdate)
    destination_store = models.ForeignKey(StoreLocation, on_delete=models.PROTECT, related_name="goods_receipts")
    destination_bin = models.ForeignKey(StorageBin, on_delete=models.PROTECT, related_name="goods_receipts", null=True, blank=True)
    source_type = models.CharField(max_length=12, choices=SOURCE_CHOICES, default="HQ")
    source_reference = models.CharField(max_length=120, blank=True)
    related_delivery_note = models.ForeignKey(DeliveryNote, on_delete=models.SET_NULL, null=True, blank=True)

    prepared_by = models.CharField(max_length=120)
    delivered_by = models.CharField(max_length=120)
    received_by = models.CharField(max_length=120)

    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default="DRAFT")
    stock_posted = models.BooleanField(default=False)
    posted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="goods_receipts_posted")
    posted_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="goods_receipts_created")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def _generate_receipt_number(self):
        stamp = timezone.localdate().strftime("%y%m")
        prefix = f"GRN-{stamp}-"
        last_doc = GoodsReceipt.objects.filter(receipt_number__startswith=prefix).order_by("-receipt_number").first()
        seq = 1
        if last_doc:
            try:
                seq = int(last_doc.receipt_number.split("-")[-1]) + 1
            except Exception:
                seq = 1
        return f"{prefix}{seq:04d}"

    def save(self, *args, **kwargs):
        if not self.receipt_number:
            self.receipt_number = self._generate_receipt_number()
        super().save(*args, **kwargs)

    def clean(self):
        errors = {}
        if not self.destination_bin_id:
            errors["destination_bin"] = "Put-away BIN is required for stock-in."
        elif self.destination_store_id and self.destination_bin.store_location_id != self.destination_store_id:
            errors["destination_bin"] = "Destination BIN must belong to selected destination store."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return self.receipt_number


class GoodsReceiptItem(models.Model):
    goods_receipt = models.ForeignKey(GoodsReceipt, on_delete=models.CASCADE, related_name="items")
    material = models.ForeignKey(Material, on_delete=models.PROTECT)
    description = models.CharField(max_length=220, blank=True)
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    is_returnable = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.material.name} x {self.quantity}"


class GoodsIssue(models.Model):
    STATUS_CHOICES = [
        ("DRAFT", "Draft"),
        ("POSTED", "Posted"),
        ("CANCELLED", "Cancelled"),
    ]

    issue_number = models.CharField(max_length=24, unique=True, blank=True)
    date_issued = models.DateField(default=timezone.localdate)
    source_store = models.ForeignKey(StoreLocation, on_delete=models.PROTECT, related_name="goods_issues")
    source_bin = models.ForeignKey(StorageBin, on_delete=models.SET_NULL, null=True, blank=True, related_name="goods_issues")
    department = models.CharField(max_length=120, blank=True)
    issued_to = models.CharField(max_length=120)
    issued_by = models.CharField(max_length=120)
    received_by = models.CharField(max_length=120)

    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default="DRAFT")
    stock_posted = models.BooleanField(default=False)
    posted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="goods_issues_posted")
    posted_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="goods_issues_created")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def _generate_issue_number(self):
        stamp = timezone.localdate().strftime("%y%m")
        prefix = f"GIS-{stamp}-"
        last_doc = GoodsIssue.objects.filter(issue_number__startswith=prefix).order_by("-issue_number").first()
        seq = 1
        if last_doc:
            try:
                seq = int(last_doc.issue_number.split("-")[-1]) + 1
            except Exception:
                seq = 1
        return f"{prefix}{seq:04d}"

    def save(self, *args, **kwargs):
        if not self.issue_number:
            self.issue_number = self._generate_issue_number()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.issue_number


class GoodsIssueItem(models.Model):
    goods_issue = models.ForeignKey(GoodsIssue, on_delete=models.CASCADE, related_name="items")
    material = models.ForeignKey(Material, on_delete=models.PROTECT)
    description = models.CharField(max_length=220, blank=True)
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    is_returnable = models.BooleanField(default=False)
    expected_return_date = models.DateField(null=True, blank=True)

    def __str__(self):
        return f"{self.material.name} x {self.quantity}"


class GoodsReturn(models.Model):
    STATUS_CHOICES = [
        ("DRAFT", "Draft"),
        ("POSTED", "Posted"),
        ("CANCELLED", "Cancelled"),
    ]

    return_number = models.CharField(max_length=24, unique=True, blank=True)
    date_returned = models.DateField(default=timezone.localdate)
    from_store = models.ForeignKey(StoreLocation, on_delete=models.SET_NULL, null=True, blank=True, related_name="goods_returns_out")
    destination_store = models.ForeignKey(StoreLocation, on_delete=models.PROTECT, related_name="goods_returns_in")
    related_goods_issue = models.ForeignKey(GoodsIssue, on_delete=models.SET_NULL, null=True, blank=True, related_name="returns")
    returned_by = models.CharField(max_length=120)
    received_by = models.CharField(max_length=120)

    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default="DRAFT")
    stock_posted = models.BooleanField(default=False)
    posted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="goods_returns_posted")
    posted_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="goods_returns_created")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def _generate_return_number(self):
        stamp = timezone.localdate().strftime("%y%m")
        prefix = f"RET-{stamp}-"
        last_doc = GoodsReturn.objects.filter(return_number__startswith=prefix).order_by("-return_number").first()
        seq = 1
        if last_doc:
            try:
                seq = int(last_doc.return_number.split("-")[-1]) + 1
            except Exception:
                seq = 1
        return f"{prefix}{seq:04d}"

    def save(self, *args, **kwargs):
        if not self.return_number:
            self.return_number = self._generate_return_number()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.return_number


class GoodsReturnItem(models.Model):
    CONDITION_CHOICES = [
        ("GOOD", "Good"),
        ("DAMAGED", "Damaged"),
        ("SCRAP", "Scrap"),
    ]

    goods_return = models.ForeignKey(GoodsReturn, on_delete=models.CASCADE, related_name="items")
    goods_issue_item = models.ForeignKey(GoodsIssueItem, on_delete=models.SET_NULL, null=True, blank=True, related_name="return_items")
    material = models.ForeignKey(Material, on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    condition = models.CharField(max_length=10, choices=CONDITION_CHOICES, default="GOOD")
    notes = models.CharField(max_length=220, blank=True)

    def __str__(self):
        return f"{self.material.name} x {self.quantity} ({self.condition})"


class PPEIssue(models.Model):
    STATUS_CHOICES = [
        ("DRAFT", "Draft"),
        ("POSTED", "Posted"),
        ("CANCELLED", "Cancelled"),
    ]
    ISSUE_TYPE_CHOICES = [
        ("FULL", "Full PPE Kit"),
        ("PARTIAL", "Partial PPE"),
        ("REPLACEMENT", "Replacement"),
    ]
    REASON_CHOICES = [
        ("NEW", "New Assignment"),
        ("LOST", "Lost"),
        ("DAMAGED", "Damaged"),
        ("WEAR", "Wear and Tear"),
    ]

    issue_number = models.CharField(max_length=24, unique=True, blank=True)
    date_issued = models.DateField(default=timezone.localdate)
    store_location = models.ForeignKey(StoreLocation, on_delete=models.PROTECT, related_name="ppe_issues")
    source_bin = models.ForeignKey(StorageBin, on_delete=models.SET_NULL, null=True, blank=True, related_name="ppe_issues")
    employee_name = models.CharField(max_length=140)
    employee_number = models.CharField(max_length=60, blank=True)
    department = models.CharField(max_length=120, blank=True)
    issue_type = models.CharField(max_length=16, choices=ISSUE_TYPE_CHOICES, default="FULL")
    reason = models.CharField(max_length=16, choices=REASON_CHOICES, default="NEW")
    approved_by = models.CharField(max_length=120, blank=True)
    issued_by = models.CharField(max_length=120)
    received_by = models.CharField(max_length=120)

    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default="DRAFT")
    stock_posted = models.BooleanField(default=False)
    posted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="ppe_issues_posted")
    posted_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="ppe_issues_created")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def _generate_issue_number(self):
        stamp = timezone.localdate().strftime("%y%m")
        prefix = f"PPE-{stamp}-"
        last_doc = PPEIssue.objects.filter(issue_number__startswith=prefix).order_by("-issue_number").first()
        seq = 1
        if last_doc:
            try:
                seq = int(last_doc.issue_number.split("-")[-1]) + 1
            except Exception:
                seq = 1
        return f"{prefix}{seq:04d}"

    def save(self, *args, **kwargs):
        if not self.issue_number:
            self.issue_number = self._generate_issue_number()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.issue_number


class PPEIssueItem(models.Model):
    ppe_issue = models.ForeignKey(PPEIssue, on_delete=models.CASCADE, related_name="items")
    material = models.ForeignKey(Material, on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    size_spec = models.CharField(max_length=60, blank=True)
    notes = models.CharField(max_length=220, blank=True)

    def __str__(self):
        return f"{self.material.name} x {self.quantity}"


class UserStoreScope(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="store_scopes")
    store_location = models.ForeignKey(StoreLocation, on_delete=models.CASCADE, related_name="user_scopes")
    can_manage = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "store_location"], name="unique_user_store_scope"),
        ]
        ordering = ["user__username", "store_location__name"]

    def __str__(self):
        return f"{self.user.username} -> {self.store_location.name}"


class AuditLog(models.Model):
    ACTION_CHOICES = [
        ("CREATE", "Create"),
        ("UPDATE", "Update"),
        ("DELETE", "Delete"),
        ("ASSIGN_ROLE", "Assign Role"),
    ]

    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    entity = models.CharField(max_length=60)
    entity_id = models.CharField(max_length=60, blank=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.action} {self.entity} ({self.entity_id})"

