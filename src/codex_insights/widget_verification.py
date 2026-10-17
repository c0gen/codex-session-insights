"""Native widget regression checks against the isolated desktop demo."""
import json


LAYOUT_CHECK = """(() => {
  const root = document.querySelector('#widget').getBoundingClientRect();
  const outside = [...document.querySelectorAll('td, tbody th')].filter(cell => {
    const range = document.createRange(); range.selectNodeContents(cell);
    const text = range.getBoundingClientRect(), box = cell.getBoundingClientRect();
    return text.left < box.left - .5 || text.right > box.right + .5 ||
      text.top < box.top - .5 || text.bottom > box.bottom + .5;
  }).map(cell => cell.textContent);
  return {width:innerWidth,height:innerHeight,scale:devicePixelRatio,
    content:[root.width,root.height], outside,
    fits:document.documentElement.scrollWidth <= innerWidth &&
      document.documentElement.scrollHeight <= innerHeight &&
      root.right <= innerWidth + .5 && root.bottom <= innerHeight + .5};
})()"""


def verify_widget(controller, widget, ui, wait_for, result):
    host = controller.native.widget_host

    def refresh():
        widget.evaluate_js("document.dispatchEvent(new Event('visibilitychange'))")

    def fits():
        value = widget.evaluate_js(LAYOUT_CHECK)
        result['widget_last_layout'] = value
        return value and value['fits'] and not value['outside']

    wait_for(fits)
    assert widget.evaluate_js("document.querySelectorAll('header, footer, nav, .pywebview-drag-region').length") == 0
    assert ui(lambda: str(widget.native.StartPosition)) == 'Manual'
    baseline = ui(lambda: (widget.native.Left, widget.native.Top))
    initial_zoom = ui(lambda: float(widget.native.webview.ZoomFactor))
    initial_scale = widget.evaluate_js('devicePixelRatio')
    scales = []
    try:
        # Exercise real WebView rendering changes without changing the user's OS settings.
        for scale in (1, 1.25, 1.5, 1.75, 1.7875, 2):
            ui(lambda: setattr(widget.native.webview, 'ZoomFactor', initial_zoom * scale / initial_scale))
            wait_for(lambda: abs(widget.evaluate_js('devicePixelRatio') - scale) < .02)
            wait_for(lambda: ui(lambda: host.layout is not None and abs(host.layout.scale - scale) < .02))
            wait_for(fits)
            scales.append(dict(result['widget_last_layout']))
    finally:
        ui(lambda: setattr(widget.native.webview, 'ZoomFactor', initial_zoom))
    wait_for(fits)
    result['widget_scales'] = scales
    result['checks'].append('native content fits at 100–200% rendering scale, including text scaling')

    all_metrics = ['tokens', 'cost', 'lines', 'chats']
    for mask in range(16):
        metrics = [metric for bit, metric in enumerate(all_metrics) if mask & (1 << bit)]
        controller.update({'metrics': metrics})
        refresh()
        wait_for(lambda: widget.evaluate_js("document.querySelectorAll('tbody tr').length") == len(metrics))
        wait_for(fits)
    controller.update({'metrics': ['tokens', 'cost', 'lines']})
    refresh()
    wait_for(lambda: widget.evaluate_js("document.querySelectorAll('tbody tr').length") == 3)
    wait_for(fits)

    widget.evaluate_js("""window.__originalWidgetCall = window.pywebview.api.call;
      window.__widgetTestMode = 'large';
      window.pywebview.api.call = async (action, args) => {
        if (action === 'widget_summary' && window.__widgetTestMode === 'offline') throw Error('Test disconnect');
        const data = await window.__originalWidgetCall(action, args);
        if (action === 'widget_summary') {
          for (const key of ['today','all_time']) Object.assign(data[key], {
            total_tokens: 1234567890123456, cost: 987654321.09, chats: 12345678,
            lines_added: 987654321, lines_removed: 123456789, change_coverage:'partial',
            priced_percent: window.__widgetTestMode === 'unpriced' ? 0 : 50
          });
          if (window.__widgetTestMode === 'error') data.job.error = 'Test update failure';
        }
        return data;
      };""")
    for mode in ('large', 'unpriced', 'error', 'offline'):
        widget.evaluate_js('window.__widgetTestMode = ' + json.dumps(mode))
        refresh()
        if mode == 'unpriced':
            wait_for(lambda: widget.evaluate_js("document.querySelector('.metric-cost').textContent.includes('Unpriced')"))
        elif mode in ('error', 'offline'):
            wait_for(lambda: widget.evaluate_js("!document.querySelector('#widget-indicator').hidden"))
            assert widget.evaluate_js("document.querySelectorAll('tbody tr').length") == 3
        else:
            wait_for(lambda: widget.evaluate_js("document.querySelector('.metric-cost').textContent.includes('987.65M')"))
        wait_for(fits)
    widget.evaluate_js("window.pywebview.api.call = window.__originalWidgetCall")
    refresh()
    wait_for(lambda: widget.evaluate_js("document.querySelector('#widget-indicator').hidden"))
    wait_for(fits)
    result['checks'].append('all 16 metric combinations, large totals, unpriced/partial costs and disconnection fit without clipping')

    from .account_widget_verification import verify_account_widget
    verify_account_widget(controller, widget, ui, wait_for, result, fits)

    from .widget_menu_verification import verify_widget_menu
    verify_widget_menu(host, widget, ui, wait_for, result)

    # Menu placement is native, so it can extend past a one-row widget.
    widget.evaluate_js("document.querySelector('#widget').dispatchEvent(new KeyboardEvent('keydown', {key:'F10',shiftKey:true,bubbles:true}))")
    wait_for(lambda: ui(lambda: host.menu is not None and host.menu.Visible))
    assert ui(lambda: [str(item.Text) for item in host.menu.Items]) == ['Open dashboard', 'Settings', 'Fit to content', 'Keep on top', 'Hide widget']
    position = ui(lambda: (widget.native.Left, widget.native.Top))
    ui(lambda: host.pin_item.PerformClick())
    ui(lambda: host.menu.Close())
    wait_for(lambda: not ui(lambda: widget.native.TopMost))
    assert ui(lambda: (widget.native.Left, widget.native.Top)) == position
    request = controller.settings_request
    ui(lambda: host.menu.Items[1].PerformClick())
    wait_for(lambda: controller.settings_request > request)
    ui(lambda: host.menu.Items[0].PerformClick())
    wait_for(lambda: ui(lambda: controller.native.window.native.Visible))
    controller.update({'widget_height_css_px': 240})
    wait_for(lambda: abs(ui(lambda: widget.native.Height) / widget.evaluate_js('devicePixelRatio') - 240) < 2)
    position = ui(lambda: (widget.native.Left, widget.native.Top))
    ui(lambda: host.menu.Items[4].PerformClick())
    wait_for(lambda: controller.native.widget is None and not controller.value['widget_enabled'])
    controller.update({'widget_enabled': True})
    wait_for(lambda: controller.native.widget is not None)
    reopened = controller.native.widget
    assert reopened.events.loaded.wait(15)
    wait_for(lambda: ui(lambda: reopened.native.Visible))
    assert ui(lambda: (reopened.native.Left, reopened.native.Top)) == position
    assert abs(ui(lambda: reopened.native.Height) / reopened.evaluate_js('devicePixelRatio') - 240) < 2
    controller.update({'widget_height_css_px': None})
    result['checks'].append('keyboard native menu, pin without movement, settings, dashboard, hide and position/custom-height restoration')
    return reopened
