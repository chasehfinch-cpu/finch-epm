"""Comprehensive registry of all known NetSuite SuiteQL record types.

This registry maps every standard NetSuite record to its SuiteQL table name,
category, and metadata. It is used by introspection to probe ALL records
exhaustively, not just the ones the current user can access.

Records have three access states:
    - ACCESSIBLE: query succeeds, columns and data are visible
    - RESTRICTED: record exists in NetSuite but the user's role lacks permission
    - NOT_FOUND: record does not exist in this NetSuite instance (wrong edition, etc.)

The registry is intentionally exhaustive. If a record type exists in any
NetSuite edition, it should be listed here so that introspection never
silently skips anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RecordCategory(Enum):
    """Categorization of NetSuite record types."""

    TRANSACTION = "transaction"
    ENTITY = "entity"
    ITEM = "item"
    DIMENSION = "dimension"
    ACCOUNTING = "accounting"
    SUPPORT = "support"
    MARKETING = "marketing"
    PROJECT = "project"
    PAYROLL = "payroll"
    MANUFACTURING = "manufacturing"
    COMMERCE = "commerce"
    SYSTEM = "system"
    CUSTOM = "custom"


class AccessStatus(Enum):
    """Access status after probing a record type."""

    ACCESSIBLE = "accessible"
    RESTRICTED = "restricted"
    NOT_FOUND = "not_found"
    UNKNOWN = "unknown"


@dataclass
class RecordTypeInfo:
    """Complete metadata for a NetSuite record type."""

    suiteql_name: str
    """PascalCase name used in SuiteQL queries."""

    rest_name: str
    """Lowercase name used in the REST metadata catalog."""

    display_name: str
    """Human-readable display name."""

    category: RecordCategory
    """Functional category."""

    is_dimension: bool = False
    """True if this is a dimensional/segment record usable for grouping."""

    supports_hierarchy: bool = False
    """True if this record has a parent column for tree structures."""

    id_column: str = "id"
    """Column used as the primary key."""

    label_column: str = "name"
    """Column used as the display label."""

    parent_column: str | None = None
    """Column containing the parent reference (if hierarchical)."""

    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProbedRecord:
    """Result of probing a record type against a live instance."""

    record: RecordTypeInfo
    status: AccessStatus
    row_count: int | None = None
    column_names: list[str] = field(default_factory=list)
    error_message: str | None = None


# =============================================================================
# COMPREHENSIVE RECORD REGISTRY
#
# Every known standard SuiteQL table name is listed here. This list was built
# from Oracle's documentation and live probing. Custom records are discovered
# dynamically via the metadata catalog and are not listed here.
# =============================================================================

STANDARD_RECORDS: list[RecordTypeInfo] = [
    # --- Core Financial Transactions ---
    RecordTypeInfo("Transaction", "transaction", "Transaction", RecordCategory.TRANSACTION),
    RecordTypeInfo("TransactionLine", "transactionline", "Transaction Line", RecordCategory.TRANSACTION),
    RecordTypeInfo("TransactionAccountingLine", "transactionaccountingline", "Transaction Accounting Line", RecordCategory.TRANSACTION),
    RecordTypeInfo("JournalEntry", "journalentry", "Journal Entry", RecordCategory.TRANSACTION),
    RecordTypeInfo("Check", "check", "Check", RecordCategory.TRANSACTION),
    RecordTypeInfo("Deposit", "deposit", "Deposit", RecordCategory.TRANSACTION),
    RecordTypeInfo("AdvIntercompanyJournalEntry", "advintercompanyjournalentry", "Adv. Intercompany Journal Entry", RecordCategory.TRANSACTION),
    RecordTypeInfo("IntercompanyJournalEntry", "intercompanyjournalentry", "Intercompany Journal Entry", RecordCategory.TRANSACTION),
    RecordTypeInfo("StatisticalJournalEntry", "statisticaljournalentry", "Statistical Journal Entry", RecordCategory.TRANSACTION),
    RecordTypeInfo("PeriodEndJournal", "periodendjournal", "Period End Journal", RecordCategory.TRANSACTION),

    # --- Sales / Revenue ---
    RecordTypeInfo("Invoice", "invoice", "Invoice", RecordCategory.TRANSACTION),
    RecordTypeInfo("CashSale", "cashsale", "Cash Sale", RecordCategory.TRANSACTION),
    RecordTypeInfo("CreditMemo", "creditmemo", "Credit Memo", RecordCategory.TRANSACTION),
    RecordTypeInfo("Estimate", "estimate", "Estimate", RecordCategory.TRANSACTION),
    RecordTypeInfo("SalesOrder", "salesorder", "Sales Order", RecordCategory.TRANSACTION),
    RecordTypeInfo("Opportunity", "opportunity", "Opportunity", RecordCategory.TRANSACTION),
    RecordTypeInfo("CashRefund", "cashrefund", "Cash Refund", RecordCategory.TRANSACTION),
    RecordTypeInfo("CustomerPayment", "customerpayment", "Customer Payment", RecordCategory.TRANSACTION),
    RecordTypeInfo("CustomerDeposit", "customerdeposit", "Customer Deposit", RecordCategory.TRANSACTION),
    RecordTypeInfo("CustomerRefund", "customerrefund", "Customer Refund", RecordCategory.TRANSACTION),
    RecordTypeInfo("ReturnAuthorization", "returnauthorization", "Return Authorization", RecordCategory.TRANSACTION),

    # --- Purchasing / AP ---
    RecordTypeInfo("PurchaseOrder", "purchaseorder", "Purchase Order", RecordCategory.TRANSACTION),
    RecordTypeInfo("VendorBill", "vendorbill", "Vendor Bill", RecordCategory.TRANSACTION),
    RecordTypeInfo("VendorCredit", "vendorcredit", "Vendor Credit", RecordCategory.TRANSACTION),
    RecordTypeInfo("VendorPayment", "vendorpayment", "Vendor Payment", RecordCategory.TRANSACTION),
    RecordTypeInfo("VendorPrepayment", "vendorprepayment", "Vendor Prepayment", RecordCategory.TRANSACTION),
    RecordTypeInfo("VendorPrepaymentApplication", "vendorprepaymentapplication", "Vendor Prepayment Application", RecordCategory.TRANSACTION),
    RecordTypeInfo("VendorReturnAuthorization", "vendorreturnauthorization", "Vendor Return Authorization", RecordCategory.TRANSACTION),
    RecordTypeInfo("PurchaseRequisition", "purchaserequisition", "Purchase Requisition", RecordCategory.TRANSACTION),
    RecordTypeInfo("ExpenseReport", "expensereport", "Expense Report", RecordCategory.TRANSACTION),
    RecordTypeInfo("CreditCardCharge", "creditcardcharge", "Credit Card Charge", RecordCategory.TRANSACTION),
    RecordTypeInfo("CreditCardRefund", "creditcardrefund", "Credit Card Refund", RecordCategory.TRANSACTION),
    RecordTypeInfo("ItemReceipt", "itemreceipt", "Item Receipt", RecordCategory.TRANSACTION),
    RecordTypeInfo("ItemFulfillment", "itemfulfillment", "Item Fulfillment", RecordCategory.TRANSACTION),
    RecordTypeInfo("BlanketPurchaseOrder", "blanketpurchaseorder", "Blanket Purchase Order", RecordCategory.TRANSACTION),
    RecordTypeInfo("PurchaseContract", "purchasecontract", "Purchase Contract", RecordCategory.TRANSACTION),

    # --- Inventory ---
    RecordTypeInfo("InventoryAdjustment", "inventoryadjustment", "Inventory Adjustment", RecordCategory.TRANSACTION),
    RecordTypeInfo("InventoryTransfer", "inventorytransfer", "Inventory Transfer", RecordCategory.TRANSACTION),
    RecordTypeInfo("InventoryCount", "inventorycount", "Inventory Count", RecordCategory.TRANSACTION),
    RecordTypeInfo("InventoryCostRevaluation", "inventorycostrevaluation", "Inventory Cost Revaluation", RecordCategory.TRANSACTION),
    RecordTypeInfo("BinTransfer", "bintransfer", "Bin Transfer", RecordCategory.TRANSACTION),
    RecordTypeInfo("BinWorksheet", "binworksheet", "Bin Worksheet", RecordCategory.TRANSACTION),
    RecordTypeInfo("TransferOrder", "transferorder", "Transfer Order", RecordCategory.TRANSACTION),
    RecordTypeInfo("IntercompanyTransferOrder", "intercompanytransferorder", "Intercompany Transfer Order", RecordCategory.TRANSACTION),
    RecordTypeInfo("InboundShipment", "inboundshipment", "Inbound Shipment", RecordCategory.TRANSACTION),

    # --- Manufacturing ---
    RecordTypeInfo("WorkOrder", "workorder", "Work Order", RecordCategory.MANUFACTURING),
    RecordTypeInfo("WorkOrderClose", "workorderclose", "Work Order Close", RecordCategory.MANUFACTURING),
    RecordTypeInfo("WorkOrderCompletion", "workordercompletion", "Work Order Completion", RecordCategory.MANUFACTURING),
    RecordTypeInfo("WorkOrderIssue", "workorderissue", "Work Order Issue", RecordCategory.MANUFACTURING),
    RecordTypeInfo("AssemblyBuild", "assemblybuild", "Assembly Build", RecordCategory.MANUFACTURING),
    RecordTypeInfo("AssemblyUnbuild", "assemblyunbuild", "Assembly Unbuild", RecordCategory.MANUFACTURING),
    RecordTypeInfo("ManufacturingCostTemplate", "manufacturingcosttemplate", "Manufacturing Cost Template", RecordCategory.MANUFACTURING),
    RecordTypeInfo("ManufacturingOperationTask", "manufacturingoperationtask", "Manufacturing Operation Task", RecordCategory.MANUFACTURING),
    RecordTypeInfo("ManufacturingRouting", "manufacturingrouting", "Manufacturing Routing", RecordCategory.MANUFACTURING),

    # --- Segments / Dimensions ---
    # Note: supports_hierarchy is a HINT from documentation. The connector
    # ALWAYS probes the parent column live, because some instances enable
    # hierarchy on dimensions that are flat in other instances.
    # parent_column="parent" is the standard NS column name for all
    # hierarchical dimensions — the connector probes whether it exists.
    RecordTypeInfo(
        "Account", "account", "Account", RecordCategory.DIMENSION,
        is_dimension=True, supports_hierarchy=True,
        label_column="accountsearchdisplayname", parent_column="parent",
    ),
    RecordTypeInfo(
        "Subsidiary", "subsidiary", "Subsidiary", RecordCategory.DIMENSION,
        is_dimension=True, supports_hierarchy=True,
        parent_column="parent",
    ),
    RecordTypeInfo(
        "Department", "department", "Department", RecordCategory.DIMENSION,
        is_dimension=True, supports_hierarchy=True,
        parent_column="parent",
    ),
    RecordTypeInfo(
        "Location", "location", "Location", RecordCategory.DIMENSION,
        is_dimension=True, supports_hierarchy=True,
        parent_column="parent",
    ),
    RecordTypeInfo(
        "Classification", "classification", "Class", RecordCategory.DIMENSION,
        is_dimension=True, supports_hierarchy=True,
        parent_column="parent",
    ),

    # --- Accounting ---
    RecordTypeInfo("AccountingPeriod", "accountingperiod", "Accounting Period", RecordCategory.ACCOUNTING),
    RecordTypeInfo("AccountingBook", "accountingbook", "Accounting Book", RecordCategory.ACCOUNTING),
    RecordTypeInfo("Currency", "currency", "Currency", RecordCategory.ACCOUNTING),
    RecordTypeInfo("CurrencyRate", "currencyrate", "Currency Rate", RecordCategory.ACCOUNTING),
    RecordTypeInfo("ConsolidatedExchangeRate", "consolidatedexchangerate", "Consolidated Exchange Rate", RecordCategory.ACCOUNTING),
    RecordTypeInfo("BudgetCategory", "budgetcategory", "Budget Category", RecordCategory.ACCOUNTING),
    RecordTypeInfo("BudgetExchangeRate", "budgetexchangerate", "Budget Exchange Rate", RecordCategory.ACCOUNTING),
    RecordTypeInfo("BudgetImport", "budgetimport", "Budget Import", RecordCategory.ACCOUNTING),
    RecordTypeInfo("Budget", "budget", "Budget", RecordCategory.ACCOUNTING),
    RecordTypeInfo("GlNumberingSequence", "glnumberingsequence", "GL Numbering Sequence", RecordCategory.ACCOUNTING),
    RecordTypeInfo("GlobalAccountMapping", "globalaccountmapping", "Global Account Mapping", RecordCategory.ACCOUNTING),
    RecordTypeInfo("ItemAccountMapping", "itemaccountmapping", "Item Account Mapping", RecordCategory.ACCOUNTING),
    RecordTypeInfo("Nexus", "nexus", "Nexus", RecordCategory.ACCOUNTING),
    RecordTypeInfo("TaxSchedule", "taxschedule", "Tax Schedule", RecordCategory.ACCOUNTING),
    RecordTypeInfo("TaxGroup", "taxgroup", "Tax Group", RecordCategory.ACCOUNTING),
    RecordTypeInfo("TaxType", "taxtype", "Tax Type", RecordCategory.ACCOUNTING),
    RecordTypeInfo("SalesTaxItem", "salestaxitem", "Sales Tax Item", RecordCategory.ACCOUNTING),
    RecordTypeInfo("TaxAcct", "taxacct", "Tax Account", RecordCategory.ACCOUNTING),
    RecordTypeInfo("Term", "term", "Payment Term", RecordCategory.ACCOUNTING),
    RecordTypeInfo("PaymentMethod", "paymentmethod", "Payment Method", RecordCategory.ACCOUNTING),
    RecordTypeInfo("PriceLevel", "pricelevel", "Price Level", RecordCategory.ACCOUNTING),
    RecordTypeInfo("PriceBook", "pricebook", "Price Book", RecordCategory.ACCOUNTING),
    RecordTypeInfo("FairValuePrice", "fairvalueprice", "Fair Value Price", RecordCategory.ACCOUNTING),
    RecordTypeInfo("FairValueFormula", "fairvalueformula", "Fair Value Formula", RecordCategory.ACCOUNTING),
    RecordTypeInfo("RevRecSchedule", "revrecschedule", "Rev Rec Schedule", RecordCategory.ACCOUNTING),
    RecordTypeInfo("RevRecTemplate", "revrectemplate", "Rev Rec Template", RecordCategory.ACCOUNTING),
    RecordTypeInfo("RevRecFieldMapping", "revrecfieldmapping", "Rev Rec Field Mapping", RecordCategory.ACCOUNTING),
    RecordTypeInfo("BillingSchedule", "billingschedule", "Billing Schedule", RecordCategory.ACCOUNTING),

    # --- Entities ---
    RecordTypeInfo("Customer", "customer", "Customer", RecordCategory.ENTITY),
    RecordTypeInfo("Vendor", "vendor", "Vendor", RecordCategory.ENTITY),
    RecordTypeInfo("Employee", "employee", "Employee", RecordCategory.ENTITY),
    RecordTypeInfo("Partner", "partner", "Partner", RecordCategory.ENTITY),
    RecordTypeInfo("Contact", "contact", "Contact", RecordCategory.ENTITY),
    RecordTypeInfo("OtherName", "othername", "Other Name", RecordCategory.ENTITY),
    RecordTypeInfo("Job", "job", "Job / Project", RecordCategory.ENTITY),
    RecordTypeInfo("EntityGroup", "entitygroup", "Entity Group", RecordCategory.ENTITY),
    RecordTypeInfo("CustomerSubsidiaryRelationship", "customersubsidiaryrelationship", "Customer-Subsidiary Relationship", RecordCategory.ENTITY),
    RecordTypeInfo("VendorSubsidiaryRelationship", "vendorsubsidiaryrelationship", "Vendor-Subsidiary Relationship", RecordCategory.ENTITY),

    # --- Items ---
    RecordTypeInfo("InventoryItem", "inventoryitem", "Inventory Item", RecordCategory.ITEM),
    RecordTypeInfo("NonInventoryPurchaseItem", "noninventorypurchaseitem", "Non-Inventory Purchase Item", RecordCategory.ITEM),
    RecordTypeInfo("NonInventoryResaleItem", "noninventoryresaleitem", "Non-Inventory Resale Item", RecordCategory.ITEM),
    RecordTypeInfo("NonInventorySaleItem", "noninventorysaleitem", "Non-Inventory Sale Item", RecordCategory.ITEM),
    RecordTypeInfo("ServicePurchaseItem", "servicepurchaseitem", "Service Purchase Item", RecordCategory.ITEM),
    RecordTypeInfo("ServiceResaleItem", "serviceresaleitem", "Service Resale Item", RecordCategory.ITEM),
    RecordTypeInfo("ServiceSaleItem", "servicesaleitem", "Service Sale Item", RecordCategory.ITEM),
    RecordTypeInfo("OtherChargePurchaseItem", "otherchargepurchaseitem", "Other Charge Purchase Item", RecordCategory.ITEM),
    RecordTypeInfo("OtherChargeResaleItem", "otherchargeresaleitem", "Other Charge Resale Item", RecordCategory.ITEM),
    RecordTypeInfo("OtherChargeSaleItem", "otherchargesaleitem", "Other Charge Sale Item", RecordCategory.ITEM),
    RecordTypeInfo("AssemblyItem", "assemblyitem", "Assembly Item", RecordCategory.ITEM),
    RecordTypeInfo("KitItem", "kititem", "Kit/Package Item", RecordCategory.ITEM),
    RecordTypeInfo("ItemGroup", "itemgroup", "Item Group", RecordCategory.ITEM),
    RecordTypeInfo("DescriptionItem", "descriptionitem", "Description Item", RecordCategory.ITEM),
    RecordTypeInfo("DiscountItem", "discountitem", "Discount Item", RecordCategory.ITEM),
    RecordTypeInfo("MarkupItem", "markupitem", "Markup Item", RecordCategory.ITEM),
    RecordTypeInfo("PaymentItem", "paymentitem", "Payment Item", RecordCategory.ITEM),
    RecordTypeInfo("SubtotalItem", "subtotalitem", "Subtotal Item", RecordCategory.ITEM),
    RecordTypeInfo("ShipItem", "shipitem", "Ship Item", RecordCategory.ITEM),
    RecordTypeInfo("DownloadItem", "downloaditem", "Download Item", RecordCategory.ITEM),
    RecordTypeInfo("GiftCertificateItem", "giftcertificateitem", "Gift Certificate Item", RecordCategory.ITEM),
    RecordTypeInfo("LotNumberedAssemblyItem", "lotnumberedassemblyitem", "Lot Numbered Assembly Item", RecordCategory.ITEM),
    RecordTypeInfo("LotNumberedInventoryItem", "lotnumberedinventoryitem", "Lot Numbered Inventory Item", RecordCategory.ITEM),
    RecordTypeInfo("SerializedAssemblyItem", "serializedassemblyitem", "Serialized Assembly Item", RecordCategory.ITEM),
    RecordTypeInfo("SerializedInventoryItem", "serializedinventoryitem", "Serialized Inventory Item", RecordCategory.ITEM),
    RecordTypeInfo("InventoryNumber", "inventorynumber", "Inventory Number", RecordCategory.ITEM),
    RecordTypeInfo("InventoryStatus", "inventorystatus", "Inventory Status", RecordCategory.ITEM),
    RecordTypeInfo("Bin", "bin", "Bin", RecordCategory.ITEM),
    RecordTypeInfo("ItemRevision", "itemrevision", "Item Revision", RecordCategory.ITEM),
    RecordTypeInfo("ItemSupplyPlan", "itemsupplyplan", "Item Supply Plan", RecordCategory.ITEM),
    RecordTypeInfo("BOM", "bom", "Bill of Materials", RecordCategory.ITEM),
    RecordTypeInfo("BOMRevision", "bomrevision", "BOM Revision", RecordCategory.ITEM),
    RecordTypeInfo("UnitsType", "unitstype", "Units Type", RecordCategory.ITEM),

    # --- Support ---
    RecordTypeInfo("SupportCase", "supportcase", "Support Case", RecordCategory.SUPPORT),
    RecordTypeInfo("SupportCaseOrigin", "supportcaseorigin", "Support Case Origin", RecordCategory.SUPPORT),
    RecordTypeInfo("SupportCasePriority", "supportcasepriority", "Support Case Priority", RecordCategory.SUPPORT),
    RecordTypeInfo("SupportCaseStatus", "supportcasestatus", "Support Case Status", RecordCategory.SUPPORT),
    RecordTypeInfo("SupportCaseType", "supportcasetype", "Support Case Type", RecordCategory.SUPPORT),
    RecordTypeInfo("Issue", "issue", "Issue", RecordCategory.SUPPORT),

    # --- CRM / Marketing ---
    RecordTypeInfo("Campaign", "campaign", "Campaign", RecordCategory.MARKETING),
    RecordTypeInfo("CampaignAudience", "campaignaudience", "Campaign Audience", RecordCategory.MARKETING),
    RecordTypeInfo("CampaignCategory", "campaigncategory", "Campaign Category", RecordCategory.MARKETING),
    RecordTypeInfo("CampaignChannel", "campaignchannel", "Campaign Channel", RecordCategory.MARKETING),
    RecordTypeInfo("CampaignFamily", "campaignfamily", "Campaign Family", RecordCategory.MARKETING),
    RecordTypeInfo("CampaignOffer", "campaignoffer", "Campaign Offer", RecordCategory.MARKETING),
    RecordTypeInfo("CampaignResponse", "campaignresponse", "Campaign Response", RecordCategory.MARKETING),
    RecordTypeInfo("CampaignTemplate", "campaigntemplate", "Campaign Template", RecordCategory.MARKETING),
    RecordTypeInfo("CampaignVertical", "campaignvertical", "Campaign Vertical", RecordCategory.MARKETING),
    RecordTypeInfo("SalesCampaign", "salescampaign", "Sales Campaign", RecordCategory.MARKETING),
    RecordTypeInfo("PromotionCode", "promotioncode", "Promotion Code", RecordCategory.MARKETING),
    RecordTypeInfo("CouponCode", "couponcode", "Coupon Code", RecordCategory.MARKETING),
    RecordTypeInfo("LeadSource", "leadsource", "Lead Source", RecordCategory.MARKETING),
    RecordTypeInfo("WinLossReason", "winlossreason", "Win/Loss Reason", RecordCategory.MARKETING),

    # --- Activities / Projects ---
    RecordTypeInfo("Task", "task", "Task", RecordCategory.PROJECT),
    RecordTypeInfo("PhoneCall", "phonecall", "Phone Call", RecordCategory.PROJECT),
    RecordTypeInfo("CalendarEvent", "calendarevent", "Calendar Event", RecordCategory.PROJECT),
    RecordTypeInfo("Message", "message", "Message", RecordCategory.PROJECT),
    RecordTypeInfo("ProjectTask", "projecttask", "Project Task", RecordCategory.PROJECT),
    RecordTypeInfo("ResourceAllocation", "resourceallocation", "Resource Allocation", RecordCategory.PROJECT),
    RecordTypeInfo("ResourceGroup", "resourcegroup", "Resource Group", RecordCategory.PROJECT),
    RecordTypeInfo("TimeBill", "timebill", "Time Entry", RecordCategory.PROJECT),
    RecordTypeInfo("TimeSheet", "timesheet", "Time Sheet", RecordCategory.PROJECT),
    RecordTypeInfo("ExpenseCategory", "expensecategory", "Expense Category", RecordCategory.PROJECT),

    # --- Payroll ---
    RecordTypeInfo("Paycheck", "paycheck", "Paycheck", RecordCategory.PAYROLL),
    RecordTypeInfo("PaycheckJournal", "paycheckjournal", "Paycheck Journal", RecordCategory.PAYROLL),
    RecordTypeInfo("PayrollItem", "payrollitem", "Payroll Item", RecordCategory.PAYROLL),
    RecordTypeInfo("HcmJob", "hcmjob", "HCM Job", RecordCategory.PAYROLL),

    # --- Commerce / Subscriptions ---
    RecordTypeInfo("Subscription", "subscription", "Subscription", RecordCategory.COMMERCE),
    RecordTypeInfo("SubscriptionChangeOrder", "subscriptionchangeorder", "Subscription Change Order", RecordCategory.COMMERCE),
    RecordTypeInfo("SubscriptionLine", "subscriptionline", "Subscription Line", RecordCategory.COMMERCE),
    RecordTypeInfo("SubscriptionPlan", "subscriptionplan", "Subscription Plan", RecordCategory.COMMERCE),
    RecordTypeInfo("SubscriptionTerm", "subscriptionterm", "Subscription Term", RecordCategory.COMMERCE),
    RecordTypeInfo("BillingAccount", "billingaccount", "Billing Account", RecordCategory.COMMERCE),
    RecordTypeInfo("BillingRevenueEvent", "billingrevenueevent", "Billing Revenue Event", RecordCategory.COMMERCE),
    RecordTypeInfo("Charge", "charge", "Charge", RecordCategory.COMMERCE),
    RecordTypeInfo("PricePlan", "priceplan", "Price Plan", RecordCategory.COMMERCE),
    RecordTypeInfo("PricingGroup", "pricinggroup", "Pricing Group", RecordCategory.COMMERCE),
    RecordTypeInfo("SalesPriceRule", "salespricerule", "Sales Price Rule", RecordCategory.COMMERCE),
    RecordTypeInfo("CommerceCategory", "commercecategory", "Commerce Category", RecordCategory.COMMERCE),
    RecordTypeInfo("SiteCategory", "sitecategory", "Site Category", RecordCategory.COMMERCE),
    RecordTypeInfo("Website", "website", "Website", RecordCategory.COMMERCE),

    # --- System / Reference ---
    RecordTypeInfo("EmailTemplate", "emailtemplate", "Email Template", RecordCategory.SYSTEM),
    RecordTypeInfo("CustomerCategory", "customercategory", "Customer Category", RecordCategory.SYSTEM),
    RecordTypeInfo("CustomerMessage", "customermessage", "Customer Message", RecordCategory.SYSTEM),
    RecordTypeInfo("CustomerStatus", "customerstatus", "Customer Status", RecordCategory.SYSTEM),
    RecordTypeInfo("VendorCategory", "vendorcategory", "Vendor Category", RecordCategory.SYSTEM),
    RecordTypeInfo("PartnerCategory", "partnercategory", "Partner Category", RecordCategory.SYSTEM),
    RecordTypeInfo("OtherNameCategory", "othernamecategory", "Other Name Category", RecordCategory.SYSTEM),
    RecordTypeInfo("ContactCategory", "contactcategory", "Contact Category", RecordCategory.SYSTEM),
    RecordTypeInfo("ContactRole", "contactrole", "Contact Role", RecordCategory.SYSTEM),
    RecordTypeInfo("NoteType", "notetype", "Note Type", RecordCategory.SYSTEM),
    RecordTypeInfo("SalesRole", "salesrole", "Sales Role", RecordCategory.SYSTEM),
    RecordTypeInfo("JobStatus", "jobstatus", "Job Status", RecordCategory.SYSTEM),
    RecordTypeInfo("JobType", "jobtype", "Job Type", RecordCategory.SYSTEM),
    RecordTypeInfo("Competitor", "competitor", "Competitor", RecordCategory.SYSTEM),
    RecordTypeInfo("CostCategory", "costcategory", "Cost Category", RecordCategory.SYSTEM),
    RecordTypeInfo("GiftCertificate", "giftcertificate", "Gift Certificate", RecordCategory.SYSTEM),
    RecordTypeInfo("PaymentCard", "paymentcard", "Payment Card", RecordCategory.SYSTEM),
    RecordTypeInfo("PaymentCardToken", "paymentcardtoken", "Payment Card Token", RecordCategory.SYSTEM),
    RecordTypeInfo("GeneralToken", "generaltoken", "General Token", RecordCategory.SYSTEM),
    RecordTypeInfo("FulfillmentRequest", "fulfillmentrequest", "Fulfillment Request", RecordCategory.SYSTEM),
    RecordTypeInfo("Usage", "usage", "Usage", RecordCategory.SYSTEM),
    RecordTypeInfo("Topic", "topic", "Topic", RecordCategory.SYSTEM),
]

# Build lookup by SuiteQL name for fast access
_BY_SUITEQL_NAME: dict[str, RecordTypeInfo] = {
    r.suiteql_name: r for r in STANDARD_RECORDS
}

# Build lookup by REST name
_BY_REST_NAME: dict[str, RecordTypeInfo] = {
    r.rest_name: r for r in STANDARD_RECORDS
}


def get_record_by_suiteql_name(name: str) -> RecordTypeInfo | None:
    """Look up a record type by its SuiteQL table name."""
    return _BY_SUITEQL_NAME.get(name)


def get_record_by_rest_name(name: str) -> RecordTypeInfo | None:
    """Look up a record type by its REST metadata catalog name."""
    return _BY_REST_NAME.get(name)


def get_all_standard_records() -> list[RecordTypeInfo]:
    """Return all known standard record types."""
    return list(STANDARD_RECORDS)


def get_dimension_records() -> list[RecordTypeInfo]:
    """Return all records marked as dimensions."""
    return [r for r in STANDARD_RECORDS if r.is_dimension]
