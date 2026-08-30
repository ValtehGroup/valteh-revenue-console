"""Add the versioned SAREMI 2026 catalog and contracted terms.

Revision ID: 20260830_12
Revises: 20260829_11
"""

from datetime import UTC, date, datetime

import sqlalchemy as sa
from alembic import op

revision = "20260830_12"
down_revision = "20260829_11"
branch_labels = None
depends_on = None


PLAN_COLUMNS = (
    sa.Column("plan_code", sa.String(80)),
    sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    sa.Column("service_line", sa.String(80), nullable=False, server_default="legacy_sigen"),
    sa.Column("status", sa.String(40), nullable=False, server_default="active"),
    sa.Column("pricing_model", sa.String(40), nullable=False, server_default="fixed"),
    sa.Column("catalog_visible", sa.Boolean(), nullable=False, server_default=sa.true()),
    sa.Column("assignable", sa.Boolean(), nullable=False, server_default=sa.true()),
    sa.Column("assignment_requires_approval", sa.Boolean(), nullable=False, server_default=sa.false()),
    sa.Column("featured", sa.Boolean(), nullable=False, server_default=sa.false()),
    sa.Column("featured_label", sa.String(80)),
    sa.Column("minimum_setup_fee", sa.Numeric(12, 2), server_default="0"),
    sa.Column("setup_type", sa.String(80)),
    sa.Column("one_time_fee", sa.Numeric(12, 2), server_default="0"),
    sa.Column("unlimited_users", sa.Boolean(), nullable=False, server_default=sa.false()),
    sa.Column("processing_description", sa.Text()),
    sa.Column("configuration_description", sa.Text()),
    sa.Column("support_description", sa.Text()),
    sa.Column("currency", sa.String(3), nullable=False, server_default="MXN"),
    sa.Column("effective_from", sa.Date()),
    sa.Column("effective_to", sa.Date()),
)

SUBSCRIPTION_COLUMNS = (
    sa.Column("contracted_monthly_fee", sa.Numeric(12, 2), nullable=False, server_default="0"),
    sa.Column("contracted_annual_fee", sa.Numeric(12, 2), nullable=False, server_default="0"),
    sa.Column("contracted_included_documents", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("contracted_overage_price", sa.Numeric(12, 2), nullable=False, server_default="0"),
    sa.Column("contracted_setup_fee", sa.Numeric(12, 2), nullable=False, server_default="0"),
    sa.Column("setup_disposition", sa.String(40), nullable=False, server_default="not_applicable"),
    sa.Column("contracted_one_time_fee", sa.Numeric(12, 2), nullable=False, server_default="0"),
    sa.Column("currency", sa.String(3), nullable=False, server_default="MXN"),
    sa.Column("billing_cycle_anchor", sa.Date()),
    sa.Column("minimum_term_months", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("renewal_review_date", sa.Date()),
    sa.Column("discount_percentage", sa.Numeric(7, 6), nullable=False, server_default="0"),
    sa.Column("discount_reason", sa.Text()),
    sa.Column("approved_by", sa.String(160)),
    sa.Column("channel_partner_code", sa.String(80)),
    sa.Column("channel_commission_pct", sa.Numeric(7, 6), nullable=False, server_default="0"),
    sa.Column("data_origin", sa.String(20), nullable=False, server_default="production"),
    sa.Column("usage_data_status", sa.String(20), nullable=False, server_default="pending"),
    sa.Column("created_at", sa.DateTime(timezone=True)),
    sa.Column("updated_at", sa.DateTime(timezone=True)),
)


def upgrade() -> None:
    connection = op.get_bind()
    _add_columns("pricing_plans", PLAN_COLUMNS)
    _add_columns("client_subscriptions", SUBSCRIPTION_COLUMNS)
    _add_usage_columns()
    _make_custom_plan_amounts_nullable()
    _backfill_legacy_plans(connection)
    _insert_saremi_plans(connection)
    _migrate_demo_subscriptions(connection)
    _backfill_contract_terms(connection)
    _mark_demo_usage()
    _create_constraints()


def _add_columns(table: str, columns: tuple[sa.Column, ...]) -> None:
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}
    for column in columns:
        if column.name not in existing:
            op.add_column(table, column)


def _add_usage_columns() -> None:
    _add_columns(
        "usage_events",
        (
            sa.Column("data_origin", sa.String(20), nullable=False, server_default="production"),
            sa.Column("environment", sa.String(20), nullable=False, server_default="production"),
            sa.Column("is_billable", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("billable_unit_id", sa.String(160)),
        ),
    )
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("usage_events")}
    if "ix_usage_events_billable_unit_id" not in indexes:
        op.create_index("ix_usage_events_billable_unit_id", "usage_events", ["billable_unit_id"])


def _make_custom_plan_amounts_nullable() -> None:
    with op.batch_alter_table("pricing_plans") as batch:
        batch.alter_column("setup_fee", existing_type=sa.Numeric(12, 2), nullable=True)
        batch.alter_column("monthly_fixed_fee", existing_type=sa.Numeric(12, 2), nullable=True)
        batch.alter_column("included_documents", existing_type=sa.Integer(), nullable=True)
        batch.alter_column("price_per_document", existing_type=sa.Numeric(12, 2), nullable=True)


def _backfill_legacy_plans(connection) -> None:
    values = {
        1: ("LEGACY_SIGEN_PILOT", "one_time"),
        2: ("LEGACY_SIGEN_GO", "fixed"),
        3: ("LEGACY_SIGEN_PLUS", "fixed"),
        4: ("LEGACY_SIGEN_PRO", "fixed"),
    }
    for plan_id, (plan_code, pricing_model) in values.items():
        connection.execute(
            sa.text(
                "UPDATE pricing_plans SET plan_code=:code, version=1, service_line='legacy_sigen', "
                "status='legacy', pricing_model=:model, catalog_visible=0, assignable=0, "
                "currency='MXN' WHERE id=:id"
            ),
            {"code": plan_code, "model": pricing_model, "id": plan_id},
        )
    connection.execute(
        sa.text(
            "UPDATE pricing_plans SET plan_code='SAREMI_PILOT_N38_2026', version=1, "
            "service_line='pilot', status='active', pricing_model='one_time', "
            "catalog_visible=0, assignable=0, assignment_requires_approval=0, setup_fee=0, "
            "minimum_setup_fee=0, setup_type='included', one_time_fee=5000, unlimited_users=1, "
            "currency='MXN' WHERE id=5"
        )
    )


def _insert_saremi_plans(connection) -> None:
    collisions = (
        connection.execute(sa.text("SELECT id FROM pricing_plans WHERE id BETWEEN 6 AND 13 ORDER BY id"))
        .scalars()
        .all()
    )
    if collisions == list(range(6, 14)):
        return
    if collisions:
        raise RuntimeError(f"Reserved SAREMI pricing-plan IDs already exist: {collisions}")

    plans = sa.table(
        "pricing_plans",
        sa.column("id", sa.Integer()),
        sa.column("name", sa.String()),
        sa.column("plan_code", sa.String()),
        sa.column("version", sa.Integer()),
        sa.column("service_line", sa.String()),
        sa.column("status", sa.String()),
        sa.column("pricing_model", sa.String()),
        sa.column("catalog_visible", sa.Boolean()),
        sa.column("assignable", sa.Boolean()),
        sa.column("assignment_requires_approval", sa.Boolean()),
        sa.column("featured", sa.Boolean()),
        sa.column("featured_label", sa.String()),
        sa.column("dedicated_client_id", sa.Integer()),
        sa.column("setup_fee", sa.Numeric()),
        sa.column("minimum_setup_fee", sa.Numeric()),
        sa.column("setup_type", sa.String()),
        sa.column("one_time_fee", sa.Numeric()),
        sa.column("annual_fee", sa.Numeric()),
        sa.column("monthly_fixed_fee", sa.Numeric()),
        sa.column("included_documents", sa.Integer()),
        sa.column("included_validations", sa.Integer()),
        sa.column("included_graph_queries", sa.Integer()),
        sa.column("included_blockchain_transactions", sa.Integer()),
        sa.column("price_per_document", sa.Numeric()),
        sa.column("price_per_validation", sa.Numeric()),
        sa.column("price_per_graph_query", sa.Numeric()),
        sa.column("price_per_blockchain_transaction", sa.Numeric()),
        sa.column("price_per_property_mint", sa.Numeric()),
        sa.column("revenue_share_percentage", sa.Numeric()),
        sa.column("unlimited_users", sa.Boolean()),
        sa.column("processing_description", sa.Text()),
        sa.column("configuration_description", sa.Text()),
        sa.column("support_description", sa.Text()),
        sa.column("currency", sa.String()),
        sa.column("effective_from", sa.Date()),
    )
    common = {
        "version": 1,
        "annual_fee": 0,
        "currency": "MXN",
        "effective_from": date(2026, 9, 1),
        "dedicated_client_id": None,
        "featured_label": None,
        "assignment_requires_approval": False,
        "included_validations": 0,
        "included_graph_queries": 0,
        "included_blockchain_transactions": 0,
        "price_per_validation": 0,
        "price_per_graph_query": 0,
        "price_per_blockchain_transaction": 0,
        "price_per_property_mint": 0,
        "revenue_share_percentage": 0,
    }
    op.bulk_insert(
        plans,
        [
            {
                **common,
                "id": 6,
                "name": "SAREMI Pilot",
                "plan_code": "SAREMI_PILOT_GENERAL_2026",
                "service_line": "pilot",
                "status": "informational",
                "pricing_model": "one_time",
                "catalog_visible": False,
                "assignable": False,
                "assignment_requires_approval": True,
                "featured": False,
                "monthly_fixed_fee": 0,
                "included_documents": 1000,
                "price_per_document": 0,
                "setup_fee": 0,
                "minimum_setup_fee": 0,
                "setup_type": "included",
                "one_time_fee": 10000,
                "unlimited_users": True,
                "processing_description": "Piloto de procesamiento documental por 30 días.",
                "configuration_description": "Alcance de piloto sujeto a aprobación.",
                "support_description": "Acompañamiento inicial; conversión esperada a Core o Scale.",
            },
            {
                **common,
                "id": 7,
                "name": "Core",
                "plan_code": "SAREMI_CORE",
                "service_line": "saremi_platform",
                "status": "active",
                "pricing_model": "fixed",
                "catalog_visible": True,
                "assignable": True,
                "featured": False,
                "monthly_fixed_fee": 6999,
                "included_documents": 1000,
                "price_per_document": 9,
                "setup_fee": 9999,
                "minimum_setup_fee": 6999,
                "setup_type": "standard",
                "one_time_fee": 0,
                "unlimited_users": True,
                "processing_description": (
                    "Extracción estructurada, validaciones, cross-checks, almacenamiento y expediente."
                ),
                "configuration_description": "Validaciones y tipos documentales estándar; dashboard base.",
                "support_description": "Soporte remoto y capacitación inicial.",
            },
            {
                **common,
                "id": 8,
                "name": "Scale",
                "plan_code": "SAREMI_SCALE",
                "service_line": "saremi_platform",
                "status": "active",
                "pricing_model": "fixed",
                "catalog_visible": True,
                "assignable": True,
                "featured": True,
                "featured_label": "Más popular",
                "monthly_fixed_fee": 11999,
                "included_documents": 2500,
                "price_per_document": 6.5,
                "setup_fee": 17999,
                "minimum_setup_fee": 14999,
                "setup_type": "advanced",
                "one_time_fee": 0,
                "unlimited_users": True,
                "processing_description": "Todo Core más mayor capacidad de configuración.",
                "configuration_description": (
                    "Nuevas reglas, tipos documentales, prellenado seleccionado y reportes avanzados según alcance."
                ),
                "support_description": "Soporte prioritario y capacitación periódica.",
            },
            {
                **common,
                "id": 9,
                "name": "Enterprise",
                "plan_code": "SAREMI_ENTERPRISE",
                "service_line": "saremi_platform",
                "status": "informational",
                "pricing_model": "custom",
                "catalog_visible": True,
                "assignable": False,
                "featured": False,
                "monthly_fixed_fee": None,
                "included_documents": None,
                "price_per_document": None,
                "setup_fee": None,
                "minimum_setup_fee": None,
                "setup_type": "custom",
                "one_time_fee": None,
                "unlimited_users": True,
                "processing_description": "Todo Scale más configuración institucional.",
                "configuration_description": "Flujos, formatos, reportes e integraciones a la medida.",
                "support_description": "Soporte dedicado, capacitación, acompañamiento on-site y SLA negociado.",
            },
            {
                **common,
                "id": 10,
                "name": "API 1K",
                "plan_code": "SAREMI_API_1K",
                "service_line": "saremi_api",
                "status": "active",
                "pricing_model": "fixed",
                "catalog_visible": True,
                "assignable": True,
                "featured": False,
                "monthly_fixed_fee": 4499,
                "included_documents": 1000,
                "price_per_document": 5,
                "setup_fee": 0,
                "minimum_setup_fee": 0,
                "setup_type": "not_applicable",
                "one_time_fee": 0,
                "unlimited_users": False,
                "processing_description": "Motor API estándar de extracción y validación.",
                "configuration_description": "Integración mediante API documentada; sin capa operativa Platform.",
                "support_description": "Credenciales y soporte de integración estándar.",
            },
            {
                **common,
                "id": 11,
                "name": "API 2.5K",
                "plan_code": "SAREMI_API_2_5K",
                "service_line": "saremi_api",
                "status": "active",
                "pricing_model": "fixed",
                "catalog_visible": True,
                "assignable": True,
                "featured": False,
                "monthly_fixed_fee": 8999,
                "included_documents": 2500,
                "price_per_document": 4,
                "setup_fee": 0,
                "minimum_setup_fee": 0,
                "setup_type": "not_applicable",
                "one_time_fee": 0,
                "unlimited_users": False,
                "processing_description": "Motor API estándar de extracción y validación para mayor volumen.",
                "configuration_description": "Integración mediante API documentada; sin capa operativa Platform.",
                "support_description": "Credenciales y soporte de integración estándar.",
            },
            {
                **common,
                "id": 12,
                "name": "API 10K",
                "plan_code": "SAREMI_API_10K",
                "service_line": "saremi_api",
                "status": "informational",
                "pricing_model": "fixed",
                "catalog_visible": True,
                "assignable": False,
                "featured": False,
                "monthly_fixed_fee": 28999,
                "included_documents": 10000,
                "price_per_document": 3.2,
                "setup_fee": 0,
                "minimum_setup_fee": 0,
                "setup_type": "not_applicable",
                "one_time_fee": 0,
                "unlimited_users": False,
                "processing_description": "Oferta API de alto volumen pendiente de validación de infraestructura.",
                "configuration_description": "Integración mediante API documentada; sin límites técnicos inventados.",
                "support_description": "Activación sujeta a revisión técnica y comercial.",
            },
            {
                **common,
                "id": 13,
                "name": "API Enterprise",
                "plan_code": "SAREMI_API_ENTERPRISE",
                "service_line": "saremi_api",
                "status": "informational",
                "pricing_model": "custom",
                "catalog_visible": True,
                "assignable": False,
                "featured": False,
                "monthly_fixed_fee": None,
                "included_documents": None,
                "price_per_document": None,
                "setup_fee": None,
                "minimum_setup_fee": None,
                "setup_type": "custom",
                "one_time_fee": None,
                "unlimited_users": False,
                "processing_description": "API para alto volumen y picos operativos negociados.",
                "configuration_description": "Términos técnicos y económicos definidos por contrato.",
                "support_description": "Soporte y SLA negociados.",
            },
        ],
    )


def _migrate_demo_subscriptions(connection) -> None:
    unexpected = (
        connection.execute(
            sa.text(
                "SELECT cs.id FROM client_subscriptions cs JOIN clients c ON c.id=cs.client_id "
                "WHERE cs.pricing_plan_id IN (1,2,3,4) AND c.client_code NOT LIKE 'test_%'"
            )
        )
        .scalars()
        .all()
    )
    if unexpected:
        raise RuntimeError(
            "Legacy Go/Plus/Pro/Pilot subscriptions exist for non-demo clients; manual review required: "
            f"{unexpected}"
        )
    connection.execute(
        sa.text(
            "UPDATE client_subscriptions SET pricing_plan_id=7, data_origin='demo', usage_data_status='demo' "
            "WHERE client_id IN (SELECT id FROM clients WHERE client_code LIKE 'test_%') "
            "AND pricing_plan_id IN (1,2,3,4)"
        )
    )


def _backfill_contract_terms(connection) -> None:
    now = datetime.now(UTC)
    connection.execute(
        sa.text(
            "UPDATE client_subscriptions SET "
            "contracted_monthly_fee=COALESCE((SELECT monthly_fixed_fee FROM pricing_plans p "
            "WHERE p.id=pricing_plan_id),0), "
            "contracted_annual_fee=COALESCE((SELECT annual_fee FROM pricing_plans p WHERE p.id=pricing_plan_id),0), "
            "contracted_included_documents=COALESCE((SELECT included_documents FROM pricing_plans p "
            "WHERE p.id=pricing_plan_id),0), "
            "contracted_overage_price=COALESCE((SELECT price_per_document FROM pricing_plans p "
            "WHERE p.id=pricing_plan_id),0), "
            "contracted_setup_fee=COALESCE((SELECT setup_fee FROM pricing_plans p WHERE p.id=pricing_plan_id),0), "
            "setup_disposition=CASE WHEN COALESCE((SELECT setup_fee FROM pricing_plans p "
            "WHERE p.id=pricing_plan_id),0)>0 "
            "THEN 'charged' ELSE 'not_applicable' END, "
            "contracted_one_time_fee=COALESCE((SELECT one_time_fee FROM pricing_plans p "
            "WHERE p.id=pricing_plan_id),0), "
            "currency=COALESCE((SELECT currency FROM pricing_plans p WHERE p.id=pricing_plan_id),'MXN'), "
            "billing_cycle_anchor=start_date, created_at=:now, updated_at=:now"
        ),
        {"now": now},
    )
    connection.execute(
        sa.text(
            "UPDATE client_subscriptions SET contracted_monthly_fee=0, contracted_annual_fee=0, "
            "contracted_included_documents=500, contracted_overage_price=0, contracted_setup_fee=0, "
            "setup_disposition='included', contracted_one_time_fee=5000, currency='MXN', "
            "billing_cycle_anchor=start_date, data_origin='production', usage_data_status='pending' "
            "WHERE pricing_plan_id=5 AND client_id=1"
        )
    )


def _mark_demo_usage() -> None:
    op.execute(
        sa.text(
            "UPDATE usage_events SET data_origin='demo', environment='sandbox', is_billable=0 "
            "WHERE imported_event_id IS NULL AND source_system IN "
            "('saremi_pilot','graphos_pilot','blockchain_pilot')"
        )
    )


def _create_constraints() -> None:
    with op.batch_alter_table("pricing_plans") as batch:
        batch.create_unique_constraint("uq_pricing_plan_code_version", ["plan_code", "version"])
        batch.create_check_constraint("ck_pricing_plans_version_positive", "version > 0")
        batch.create_check_constraint(
            "ck_pricing_plans_status", "status IN ('active','informational','legacy','retired')"
        )
        batch.create_check_constraint("ck_pricing_plans_model", "pricing_model IN ('fixed','custom','one_time')")
        batch.create_check_constraint(
            "ck_pricing_plans_dates", "effective_to IS NULL OR effective_from IS NULL OR effective_to >= effective_from"
        )
        batch.create_check_constraint(
            "ck_pricing_plans_non_negative",
            "COALESCE(setup_fee,0)>=0 AND COALESCE(minimum_setup_fee,0)>=0 AND "
            "COALESCE(one_time_fee,0)>=0 AND annual_fee>=0 AND COALESCE(monthly_fixed_fee,0)>=0 AND "
            "COALESCE(included_documents,0)>=0 AND COALESCE(price_per_document,0)>=0",
        )
    with op.batch_alter_table("client_subscriptions") as batch:
        batch.create_check_constraint(
            "ck_client_subscriptions_setup_disposition",
            "setup_disposition IN ('charged','included','waived','not_applicable')",
        )
        batch.create_check_constraint("ck_client_subscriptions_data_origin", "data_origin IN ('production','demo')")
        batch.create_check_constraint(
            "ck_client_subscriptions_usage_status", "usage_data_status IN ('pending','available','demo')"
        )
        batch.create_check_constraint("ck_client_subscriptions_dates", "end_date IS NULL OR end_date >= start_date")
        batch.create_check_constraint(
            "ck_client_subscriptions_non_negative",
            "contracted_monthly_fee>=0 AND contracted_annual_fee>=0 AND contracted_included_documents>=0 "
            "AND contracted_overage_price>=0 AND contracted_setup_fee>=0 AND contracted_one_time_fee>=0 "
            "AND minimum_term_months>=0 AND discount_percentage>=0 AND channel_commission_pct>=0",
        )
        batch.create_check_constraint(
            "ck_client_subscriptions_zero_unbilled_setup",
            "setup_disposition='charged' OR contracted_setup_fee=0",
        )
    with op.batch_alter_table("usage_events") as batch:
        batch.create_check_constraint("ck_usage_events_data_origin", "data_origin IN ('production','demo')")
        batch.create_check_constraint(
            "ck_usage_events_environment",
            "environment IN ('production','staging','development','sandbox','internal')",
        )


def downgrade() -> None:
    connection = op.get_bind()
    non_demo_refs = (
        connection.execute(
            sa.text(
                "SELECT id FROM client_subscriptions WHERE pricing_plan_id BETWEEN 6 AND 13 "
                "AND data_origin <> 'demo'"
            )
        )
        .scalars()
        .all()
    )
    if non_demo_refs:
        raise RuntimeError(
            "Cannot downgrade SAREMI pricing catalog while production agreements reference it: " f"{non_demo_refs}"
        )
    connection.execute(
        sa.text("UPDATE client_subscriptions SET pricing_plan_id=2 WHERE pricing_plan_id=7 AND data_origin='demo'")
    )
    connection.execute(sa.text("DELETE FROM pricing_plans WHERE id BETWEEN 6 AND 13"))
    connection.execute(sa.text("UPDATE pricing_plans SET setup_fee=5000 WHERE id=5"))
    with op.batch_alter_table("usage_events") as batch:
        batch.drop_constraint("ck_usage_events_environment", type_="check")
        batch.drop_constraint("ck_usage_events_data_origin", type_="check")
    op.drop_index("ix_usage_events_billable_unit_id", table_name="usage_events")
    for column in ("billable_unit_id", "is_billable", "environment", "data_origin"):
        op.drop_column("usage_events", column)
    with op.batch_alter_table("client_subscriptions") as batch:
        batch.drop_constraint("ck_client_subscriptions_zero_unbilled_setup", type_="check")
        batch.drop_constraint("ck_client_subscriptions_non_negative", type_="check")
        batch.drop_constraint("ck_client_subscriptions_dates", type_="check")
        batch.drop_constraint("ck_client_subscriptions_usage_status", type_="check")
        batch.drop_constraint("ck_client_subscriptions_data_origin", type_="check")
        batch.drop_constraint("ck_client_subscriptions_setup_disposition", type_="check")
    for column in reversed([column.name for column in SUBSCRIPTION_COLUMNS]):
        op.drop_column("client_subscriptions", column)
    with op.batch_alter_table("pricing_plans") as batch:
        batch.drop_constraint("ck_pricing_plans_non_negative", type_="check")
        batch.drop_constraint("ck_pricing_plans_dates", type_="check")
        batch.drop_constraint("ck_pricing_plans_model", type_="check")
        batch.drop_constraint("ck_pricing_plans_status", type_="check")
        batch.drop_constraint("ck_pricing_plans_version_positive", type_="check")
        batch.drop_constraint("uq_pricing_plan_code_version", type_="unique")
    for column in reversed([column.name for column in PLAN_COLUMNS]):
        op.drop_column("pricing_plans", column)
    with op.batch_alter_table("pricing_plans") as batch:
        batch.alter_column("setup_fee", existing_type=sa.Numeric(12, 2), nullable=False)
        batch.alter_column("monthly_fixed_fee", existing_type=sa.Numeric(12, 2), nullable=False)
        batch.alter_column("included_documents", existing_type=sa.Integer(), nullable=False)
        batch.alter_column("price_per_document", existing_type=sa.Numeric(12, 2), nullable=False)
