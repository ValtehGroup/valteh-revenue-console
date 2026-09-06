(function () {
  "use strict";
  const pointers = new WeakMap();
  const recordPointer = event => {
    const graph = event.target.closest?.(".chart-shell .dash-graph");
    if (!graph) return;
    const rect = graph.getBoundingClientRect();
    pointers.set(graph, {x0: event.clientX - rect.left, x1: event.clientX - rect.left,
      y0: event.clientY - rect.top, y1: event.clientY - rect.top});
  };
  if (!window.__valtehChartPointerListeners) {
    document.addEventListener("pointerover", recordPointer, true);
    document.addEventListener("pointermove", recordPointer, true);
    window.__valtehChartPointerListeners = true;
  }

  const element = (type, children, className) => ({
    namespace: "dash_html_components", type, props: {children: String(children), className}
  });
  const valueRows = figure => {
    const rows = (figure?.data || []).flatMap(trace => trace.customdata || []);
    if (!rows.length) return element("Div", "No data for this view", "chart-empty-value");
    return {
      namespace: "dash_html_components", type: "Dl", props: {children: rows.map(row => ({
        namespace: "dash_html_components", type: "Div", props: {
          className: "chart-value-row", children: [
            element("Dt", [row[0], row[1]].filter(Boolean).join(" · "), ""),
            element("Dd", row[3], "")
          ]
        }
      }))}
    };
  };

  window.dash_clientside = window.dash_clientside || {};
  window.dash_clientside.valtehCharts = {
    tooltip: function (hover, figure) {
      const hidden = [false, {}, [], "bottom"];
      const triggers = window.dash_clientside.callback_context.triggered || [];
      if (triggers.some(item => item.prop_id.endsWith(".figure"))) {
        return [...hidden, valueRows(figure)];
      }
      const point = hover?.points?.[0];
      const metadata = point?.customdata;
      if (!point || !Array.isArray(metadata) || metadata.length < 4) {
        return [...hidden, window.dash_clientside.no_update];
      }
      const graphId = triggers[0]?.prop_id.split(".")[0];
      const graph = graphId && document.getElementById(graphId);
      const anchor = point.bbox || (graph && pointers.get(graph));
      if (!anchor) return [...hidden, window.dash_clientside.no_update];
      const children = [element("Div", metadata[0], "chart-tooltip-title")];
      if (metadata[1]) children.push(element("Div", metadata[1], "chart-tooltip-context"));
      children.push(element("Div", metadata[2], "chart-tooltip-label"));
      children.push(element("Div", metadata[3], "chart-tooltip-value"));
      const rect = graph?.getBoundingClientRect();
      const bbox = {...anchor};
      if (rect) {
        const center = (bbox.x0 + bbox.x1) / 2;
        const right = Math.min(window.innerWidth, rect.right ?? window.innerWidth);
        const clamped = Math.max(128, Math.min(center, right - rect.left - 128));
        bbox.x0 += clamped - center;
        bbox.x1 += clamped - center;
      }
      const direction = rect && rect.top + bbox.y1 + 150 > window.innerHeight ? "top" : "bottom";
      return [true, bbox, children, direction, window.dash_clientside.no_update];
    }
  };
})();
