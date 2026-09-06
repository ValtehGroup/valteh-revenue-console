(function () {
  "use strict";
  const grid = window.dashAgGridFunctions = window.dashAgGridFunctions || {};
  const valid = value => typeof value === "number" && Number.isFinite(value);
  const numberFormat = decimals => new Intl.NumberFormat("en-US", {
    minimumFractionDigits: decimals, maximumFractionDigits: decimals
  });

  grid.valtehNumber = (params, decimals = 2) => valid(params.value)
    ? numberFormat(decimals).format(params.value) : "\u2014";
  grid.valtehInteger = params => valid(params.value) ? numberFormat(0).format(params.value) : "\u2014";
  grid.valtehDecimal = (params, decimals = 4) => valid(params.value)
    ? numberFormat(decimals).format(params.value) : "\u2014";
  grid.valtehMoney = (params, currency = "MXN", decimals = 2) => valid(params.value)
    ? "$" + numberFormat(decimals).format(params.value) + " " + currency : "\u2014";
  grid.valtehRowMoney = (params, decimals = 2) => valid(params.value)
    ? "$" + numberFormat(decimals).format(params.value) + " " + (params.data?.currency || "MXN") : "\u2014";
  grid.valtehPercent = params => valid(params.value)
    ? new Intl.NumberFormat("en-US", {style: "percent", minimumFractionDigits: 1, maximumFractionDigits: 1})
      .format(params.value) : "\u2014";
  grid.valtehBoolean = params => params.value === true ? "Yes" : params.value === false ? "No" : "\u2014";
  grid.valtehStatusClass = params => {
    const status = String(params.value ?? "").toLowerCase();
    if (["active", "resolved"].includes(status)) return "grid-status-active";
    if (status === "inactive") return "grid-status-inactive";
    if (["ended", "unknown", "unresolved"].includes(status)) return "grid-status-warning";
    return "";
  };
  grid.valtehUsage = params => {
    if (valid(params.value)) return numberFormat(0).format(params.value);
    const labels = {pending: "Pending integration", demo: "Demo", unavailable: "\u2014"};
    return labels[params.data?.monthly_usage_status] || "\u2014";
  };
  grid.valtehCatalogMoney = (params, decimals = 0) => valid(params.value)
    ? "$" + numberFormat(decimals).format(params.value) + " MXN" : "A la medida";
  grid.valtehCatalogQuantity = params => valid(params.value)
    ? numberFormat(0).format(params.value) : "According to operation";
  grid.valtehCatalogSetup = params => params.data?.setup_label || "A la medida";
  grid.valtehLookup = params => {
    const labels = params.colDef.cellEditorParams?.labels || {};
    return labels[String(params.value ?? "")] ?? String(params.value ?? "\u2014");
  };
  grid.valtehGridTheme = theme => theme.withParams({
    backgroundColor: "var(--color-surface)", foregroundColor: "var(--color-text)",
    headerBackgroundColor: "var(--color-surface-elevated)", headerTextColor: "var(--color-text)",
    borderColor: "var(--color-border)", accentColor: "var(--color-primary)",
    oddRowBackgroundColor: "var(--color-row-alt)", rowHoverColor: "var(--color-row-hover)",
    selectedRowBackgroundColor: "var(--color-surface-soft)", inputBackgroundColor: "var(--color-surface)",
    fontFamily: "var(--font-family)", fontSize: 13, wrapperBorderRadius: 8, spacing: 6
  });
})();
