from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

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
    name = models.CharField(max_length=100)
    subcategory = models.ForeignKey(SubCategory, on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.name} ({self.subcategory.name})"

class Material(models.Model):
    name = models.CharField(max_length=100)
    code_number = models.CharField(max_length=50, unique=True, default='UNKNOWN')  # Add unique=True
    part_number = models.CharField(max_length=50, unique=True, null=True, blank=True)  # Optional
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

class Requisition(models.Model):
    code_number = models.CharField(max_length=50, default='UNKNOWN')
    material = models.ForeignKey(Material, on_delete=models.CASCADE, null=True, blank=True)
    quantity_requested = models.PositiveIntegerField()
    department = models.CharField(max_length=10, choices=DEPARTMENTS)
    project = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True, blank=True)  # New field
    requested_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='requested_by')
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_by')
    date_requested = models.DateTimeField(default=timezone.now)
    fulfilled = models.BooleanField(default=False)
    notes = models.TextField(blank=True)

    def save(self, *args, **kwargs):
        if self.code_number:
            try:
                self.material = Material.objects.get(code_number=self.code_number)
            except Material.DoesNotExist:
                self.material = None
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.department}: {self.quantity_requested} {self.material.unit if self.material else ''} of {self.material.name if self.material else 'Unknown'} for {self.project.name if self.project else 'No Project'}"

    @property
    def code_number_display(self):
        return self.material.code_number if self.material else self.code_number

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

