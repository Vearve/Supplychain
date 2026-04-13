from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from .models import (
	Category,
	DeliveryNote,
	Equipment,
	InventoryBalance,
	InventoryMovement,
	Material,
	PPEIssue,
	PPEIssueItem,
	Project,
	Requisition,
	RequisitionItem,
	StorageBin,
	StoreLocation,
	SubCategory,
	UserStoreScope,
)


class WorkspaceRegressionTests(TestCase):
	def setUp(self):
		self.storekeeper_group, _ = Group.objects.get_or_create(name="Storekeeper")
		self.ops_manager_group, _ = Group.objects.get_or_create(name="Operations Manager")

		self.storekeeper = User.objects.create_user(username="keeper", password="pass1234")
		self.storekeeper.groups.add(self.storekeeper_group)

		self.ops_manager = User.objects.create_user(username="ops", password="pass1234")
		self.ops_manager.groups.add(self.ops_manager_group)

		self.project_a = Project.objects.create(name="Site A")
		self.project_b = Project.objects.create(name="Site B")

		self.store_a = StoreLocation.objects.create(name="Store A", location_type="SITE", project=self.project_a)
		self.store_b = StoreLocation.objects.create(name="Store B", location_type="SITE", project=self.project_b)

		self.category = Category.objects.create(name="Safety")
		self.subcategory = SubCategory.objects.create(name="PPE", category=self.category)
		self.material = Material.objects.create(
			name="Helmet",
			code_number="MAT-HELMET-001",
			category=self.category,
			subcategory=self.subcategory,
			unit="pcs",
			quantity=100,
			min_required=5,
		)

	def test_store_scope_page_requires_ops_manager(self):
		self.client.force_login(self.storekeeper)
		denied = self.client.get(reverse("store_scope"))
		self.assertEqual(denied.status_code, 403)

		self.client.force_login(self.ops_manager)
		allowed = self.client.get(reverse("store_scope"))
		self.assertEqual(allowed.status_code, 200)

	def test_equipment_view_and_detail_are_scoped_by_store(self):
		UserStoreScope.objects.create(user=self.storekeeper, store_location=self.store_a, can_manage=False)

		visible_eq = Equipment.objects.create(name="Compressor A", subcategory=self.subcategory, store_location=self.store_a)
		hidden_eq = Equipment.objects.create(name="Compressor B", subcategory=self.subcategory, store_location=self.store_b)

		self.client.force_login(self.storekeeper)
		response = self.client.get(reverse("equipment_management"))

		self.assertContains(response, visible_eq.name)
		self.assertNotContains(response, hidden_eq.name)

		hidden_detail = self.client.get(reverse("equipment_detail", args=[hidden_eq.id]))
		self.assertEqual(hidden_detail.status_code, 404)

	def test_ppe_post_creates_inventory_movement_and_deducts_stock(self):
		UserStoreScope.objects.create(user=self.storekeeper, store_location=self.store_a, can_manage=True)
		source_bin = StorageBin.objects.create(store_location=self.store_a)
		balance = InventoryBalance.objects.create(
			material=self.material,
			storage_bin=source_bin,
			on_hand=Decimal("10.00"),
			reserved=Decimal("0.00"),
		)

		ppe = PPEIssue.objects.create(
			store_location=self.store_a,
			source_bin=source_bin,
			employee_name="Field Tech",
			issued_by="Warehouse",
			received_by="Field Tech",
			created_by=self.storekeeper,
			status="DRAFT",
		)
		PPEIssueItem.objects.create(ppe_issue=ppe, material=self.material, quantity=Decimal("2.00"))

		self.client.force_login(self.storekeeper)
		post_resp = self.client.post(reverse("ppe_issues"), {"ppe_id": ppe.id, "action": "post"})
		self.assertEqual(post_resp.status_code, 302)

		ppe.refresh_from_db()
		balance.refresh_from_db()

		self.assertEqual(ppe.status, "POSTED")
		self.assertTrue(ppe.stock_posted)
		self.assertEqual(balance.on_hand, Decimal("8.00"))
		self.assertTrue(
			InventoryMovement.objects.filter(
				reference_type="PPE_ISSUE",
				reference_number=ppe.issue_number,
				material=self.material,
			).exists()
		)

	def test_ops_overview_metrics_respect_store_scope(self):
		UserStoreScope.objects.create(user=self.storekeeper, store_location=self.store_a, can_manage=False)

		req_a = Requisition.objects.create(
			material=self.material,
			code_number=self.material.code_number,
			quantity_requested=3,
			department="SITE",
			project=self.project_a,
			requested_by=self.storekeeper,
			status="SUBMITTED",
		)
		req_b = Requisition.objects.create(
			material=self.material,
			code_number=self.material.code_number,
			quantity_requested=4,
			department="SITE",
			project=self.project_b,
			requested_by=self.storekeeper,
			status="SUBMITTED",
		)

		DeliveryNote.objects.create(
			from_location="HQ",
			to_location="Site A",
			prepared_by="Planner",
			delivered_by="Driver",
			received_by="Receiver",
			source_requisition=req_a,
			status="DISPATCHED",
		)
		DeliveryNote.objects.create(
			from_location="HQ",
			to_location="Site B",
			prepared_by="Planner",
			delivered_by="Driver",
			received_by="Receiver",
			source_requisition=req_b,
			status="DISPATCHED",
		)

		bin_a = StorageBin.objects.create(store_location=self.store_a)
		bin_b = StorageBin.objects.create(store_location=self.store_b)
		InventoryBalance.objects.create(material=self.material, storage_bin=bin_a, on_hand=Decimal("5.00"), reserved=Decimal("1.00"))
		InventoryBalance.objects.create(material=self.material, storage_bin=bin_b, on_hand=Decimal("7.00"), reserved=Decimal("2.00"))

		Equipment.objects.create(name="Generator A", subcategory=self.subcategory, store_location=self.store_a)
		Equipment.objects.create(name="Generator B", subcategory=self.subcategory, store_location=self.store_b)

		self.client.force_login(self.storekeeper)
		response = self.client.get(reverse("ops_overview"))

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.context["active_store_count"], 1)
		self.assertEqual(response.context["delivery_dispatched"], 1)
		self.assertEqual(response.context["pending_requisitions"], 1)
		self.assertEqual(response.context["stock_line_count"], 1)
		self.assertEqual(response.context["equipment_linked_count"], 1)

	def test_multi_item_requisition_approve_reserves_per_line(self):
		"""Approving a multi-item requisition creates one RequisitionReservation per item line."""
		material2 = Material.objects.create(
			name="Gloves",
			code_number="MAT-GLOVES-001",
			category=self.category,
			subcategory=self.subcategory,
			unit="pairs",
			quantity=50,
			min_required=2,
		)

		hq_store = StoreLocation.objects.create(name="HQ Warehouse", location_type="HQ")
		hq_bin1 = StorageBin.objects.create(store_location=hq_store)
		hq_bin2 = StorageBin.objects.create(store_location=hq_store)
		InventoryBalance.objects.create(
			material=self.material, storage_bin=hq_bin1, on_hand=Decimal("10.00"), reserved=Decimal("0.00")
		)
		InventoryBalance.objects.create(
			material=material2, storage_bin=hq_bin2, on_hand=Decimal("20.00"), reserved=Decimal("0.00")
		)

		req = Requisition.objects.create(
			quantity_requested=0,
			department="SITE",
			project=self.project_a,
			requested_by=self.storekeeper,
			status="SUBMITTED",
		)
		RequisitionItem.objects.create(requisition=req, material=self.material, quantity_requested=Decimal("3.00"))
		RequisitionItem.objects.create(requisition=req, material=material2, quantity_requested=Decimal("5.00"))

		self.client.force_login(self.ops_manager)
		resp = self.client.post(reverse("requisitions"), {"requisition_id": req.id, "action": "approve"})
		self.assertEqual(resp.status_code, 302)

		req.refresh_from_db()
		self.assertEqual(req.status, "APPROVED")
		self.assertEqual(req.reservations.count(), 2)
		reserved_mat_ids = set(req.reservations.values_list("inventory_balance__material_id", flat=True))
		self.assertIn(self.material.id, reserved_mat_ids)
		self.assertIn(material2.id, reserved_mat_ids)

	def test_project_scoped_goods_received_create_filters_stores(self):
		"""GET goods_received_create?project=<pk> filters destination_store to that project's stores."""
		self.client.force_login(self.ops_manager)
		url = reverse("goods_received_create") + f"?project={self.project_a.id}"
		response = self.client.get(url)
		self.assertEqual(response.status_code, 200)

		form = response.context["form"]
		store_ids = list(form.fields["destination_store"].queryset.values_list("id", flat=True))
		self.assertIn(self.store_a.id, store_ids)
		self.assertNotIn(self.store_b.id, store_ids)

	def test_project_manage_page_loads_with_counts(self):
		"""project_manage page returns 200 and exposes req_count for the project."""
		Requisition.objects.create(
			quantity_requested=2,
			department="SITE",
			project=self.project_a,
			requested_by=self.storekeeper,
			status="SUBMITTED",
		)
		self.client.force_login(self.ops_manager)
		url = reverse("project_manage", args=[self.project_a.id])
		response = self.client.get(url)
		self.assertEqual(response.status_code, 200)
		self.assertGreaterEqual(response.context["req_count"], 1)
