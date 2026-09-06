const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const gridSource = fs.readFileSync('app/assets/grid.js', 'utf8');
const chartSource = fs.readFileSync('app/assets/chart-shell.js', 'utf8');

function setup() {
  const window = {innerWidth: 390, innerHeight: 600, dash_clientside: {callback_context: {triggered: [{prop_id:'chart.hoverData'}]}}};
  const graph = {getBoundingClientRect: () => ({left: 0, top: 400})};
  const listeners = {};
  const context = {window, Intl, document: {addEventListener: (name, fn) => {listeners[name] = fn;}, getElementById: () => graph}};
  vm.runInNewContext(gridSource, context);
  vm.runInNewContext(chartSource, context);
  window.recordPointer = () => listeners.pointerover({target: {closest: () => graph}, clientX: 200, clientY: 450});
  return window;
}

test('numeric formatters preserve zero, negatives, percentages and absent values', () => {
  const grid = setup().dashAgGridFunctions;
  assert.equal(grid.valtehMoney({value: 0}), '$0.00 MXN');
  assert.equal(grid.valtehMoney({value: -1234.56}, 'USD'), '$-1,234.56 USD');
  assert.equal(grid.valtehMoney({value: null}), '\u2014');
  assert.equal(grid.valtehMoney({value: NaN}), '\u2014');
  assert.equal(grid.valtehPercent({value: -0.123}), '-12.3%');
  assert.equal(grid.valtehInteger({value: 1234567}), '1,234,567');
  assert.equal(grid.valtehDecimal({value: 18.4725}), '18.4725');
});

test('row-aware and lookup formatters preserve values and labels as plain text', () => {
  const grid = setup().dashAgGridFunctions;
  assert.equal(grid.valtehRowMoney({value: -5, data: {currency: 'USD'}}), '$-5.00 USD');
  assert.equal(grid.valtehBoolean({value: false}), 'No');
  const label = '<b>Client</b>';
  const params = {value: 7, colDef: {cellEditorParams: {labels: {'7': label}}}};
  assert.equal(grid.valtehLookup(params), label);
  assert.equal(grid.valtehLookup({value: null, colDef: {cellEditorParams: {labels: {}}}}), '\u2014');
});

test('status classes distinguish active, inactive and warning states', () => {
  const grid = setup().dashAgGridFunctions;
  assert.equal(grid.valtehStatusClass({value: 'active'}), 'grid-status-active');
  assert.equal(grid.valtehStatusClass({value: 'inactive'}), 'grid-status-inactive');
  assert.equal(grid.valtehStatusClass({value: 'ended'}), 'grid-status-warning');
  assert.equal(grid.valtehStatusClass({value: '<b>active</b>'}), '');
});

test('grid theme derives the same parameters on repeated evaluation', () => {
  const grid = setup().dashAgGridFunctions;
  const theme = {withParams: params => params};
  assert.deepEqual(grid.valtehGridTheme(theme), grid.valtehGridTheme(theme));
});

test('tooltip clears on unhover, missing point and figure replacement', () => {
  const window = setup();
  const tooltip = window.dash_clientside.valtehCharts.tooltip;
  assert.equal(tooltip(null, {} )[0], false);
  assert.equal(tooltip({points:[]}, {} )[0], false);
  window.dash_clientside.callback_context.triggered = [{prop_id:'chart.figure'}];
  const refreshed = tooltip(
    {points:[{bbox:{x0:0,x1:20,y0:10,y1:20},pointNumber:0}]},
    {data:[
      {customdata:[['Production','2026-08-20','Tokens','1,234,567']]},
      {customdata:[['Base','2026-08','Operating margin','$0.00 MXN']]}
    ]}
  );
  assert.equal(refreshed[0], false);
  assert.equal(refreshed[4].props.children.length, 2);
  assert.equal(refreshed[4].props.children[0].props.children[1].props.children, '1,234,567');
  assert.equal(refreshed[4].props.children[1].props.children[1].props.children, '$0.00 MXN');
});

test('tooltip uses safe text, exact currency and viewport-aware position', () => {
  const tooltip = setup().dash_clientside.valtehCharts.tooltip;
  const label = '<script>alert(1)</script>';
  const metadata = [label, 'August 2026', 'Margin', '$-1,234.56 USD'];
  const hover = {points:[{bbox:{x0:360,x1:380,y0:150,y1:160},pointNumber:0,customdata:metadata}]};
  const result = tooltip(hover,{data:[{customdata:[metadata]}],layout:{title:{text:'Margin'}}});
  assert.equal(result[0], true);
  assert.equal(result[2][0].props.children, label);
  assert.equal(result[2][3].props.children, '$-1,234.56 USD');
  assert.equal(result[3], 'top');
  assert.ok((result[1].x0+result[1].x1)/2 <= 270);
  assert.equal(hover.points[0].bbox.x0,360);
});

test('pie tooltip anchors pointer when Plotly omits bbox with native hover disabled', () => {
  const window = setup();
  window.recordPointer();
  const metadata = ['SAREMI', '', 'Revenue', '$1,234.56 MXN'];
  const result = window.dash_clientside.valtehCharts.tooltip(
    {points:[{pointNumbers:[0],label:'SAREMI',customdata:metadata}]},
    {data:[{customdata:[metadata]}],layout:{title:{text:'Revenue'}}}
  );
  assert.equal(result[0], true);
  assert.equal(result[1].x0, 200);
  assert.equal(result[1].y0, 50);
  assert.equal(result[2][2].props.children, '$1,234.56 MXN');
});

test('tooltip preserves exact token, percentage and FX display values', () => {
  const tooltip = setup().dash_clientside.valtehCharts.tooltip;
  for (const [metric, value] of [['Tokens', '1,234,567'], ['Margin', '-12.3%'], ['USD/MXN FIX', '18.4725']]) {
    const metadata = ['Series', '2026-08-20', metric, value];
    const result = tooltip({points:[{bbox:{x0:10,x1:20,y0:10,y1:20},customdata:metadata}]}, {});
    assert.equal(result[0], true);
    assert.equal(result[2][3].props.children, value);
  }
});

test('global pointer listeners are initialized once', () => {
  const window = {innerWidth: 390, innerHeight: 600, dash_clientside: {callback_context: {triggered: []}}};
  let listenerCount = 0;
  const context = {window, Intl, document: {addEventListener: () => {listenerCount += 1;}, getElementById: () => null}};
  vm.runInNewContext(chartSource, context);
  vm.runInNewContext(chartSource, context);
  assert.equal(listenerCount, 2);
});
